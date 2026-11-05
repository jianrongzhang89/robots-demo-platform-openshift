#include "demo_semantic_costmap/semantic_layer.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <sstream>
#include <openssl/sha.h>
#include <nav2_costmap_2d/layered_costmap.hpp>
#include <pluginlib/class_list_macros.hpp>
#include <rclcpp/rclcpp.hpp>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>

namespace demo_semantic_costmap
{
using Json = nlohmann::json;
using nav2_costmap_2d::NO_INFORMATION;
static int64_t stampNs(const std_msgs::msg::Header & h)
{return static_cast<int64_t>(h.stamp.sec) * 1000000000LL + h.stamp.nanosec;}

int64_t SemanticLayer::wallNow() const
{
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
    std::chrono::system_clock::now().time_since_epoch()).count();
}
int64_t SemanticLayer::simNow() const {return clock_->now().nanoseconds();}
std::string SemanticLayer::digest(const std::vector<uint8_t> & data)
{
  unsigned char bytes[SHA256_DIGEST_LENGTH];
  SHA256(data.data(), data.size(), bytes);
  std::ostringstream text;
  for (auto byte : bytes) {text << std::hex << std::setw(2) << std::setfill('0') << int(byte);}
  return text.str();
}

void SemanticLayer::onInitialize()
{
  auto node = node_.lock();
  if (!node) {throw std::runtime_error("missing lifecycle node");}
  declareParameter("enabled", rclcpp::ParameterValue(true));
  declareParameter("topic_prefix", rclcpp::ParameterValue("/robot_1/semantic"));
  declareParameter("observation_lifetime", rclcpp::ParameterValue(1.0));
  declareParameter("max_capture_age", rclcpp::ParameterValue(0.5));
  declareParameter("target_cost", rclcpp::ParameterValue(200));
  declareParameter("optical_frame", rclcpp::ParameterValue(frame_));
  declareParameter("min_height", rclcpp::ParameterValue(min_height_));
  declareParameter("max_height", rclcpp::ParameterValue(max_height_));
  declareParameter("max_range", rclcpp::ParameterValue(max_range_));
  auto param = [&](const char * key) {return node->get_parameter(name_ + "." + key);};
  enabled_ = param("enabled").as_bool();
  double ttl = param("observation_lifetime").as_double();
  double age = param("max_capture_age").as_double();
  int cost = param("target_cost").as_int();
  min_height_ = param("min_height").as_double(); max_height_ = param("max_height").as_double();
  max_range_ = param("max_range").as_double(); frame_ = param("optical_frame").as_string();
  if (!std::isfinite(ttl) || ttl <= 0 || ttl > 5 || !std::isfinite(age) || age <= 0 || age > ttl ||
    cost < 1 || cost > 254 || !std::isfinite(min_height_) || !std::isfinite(max_height_) ||
    min_height_ > max_height_ || !std::isfinite(max_range_) || max_range_ <= 0 || frame_.empty())
  {throw std::invalid_argument("invalid semantic policy parameters");}
  ttl_ns_ = int64_t(ttl * 1e9); max_age_ns_ = int64_t(age * 1e9); target_cost_ = cost;
  default_value_ = NO_INFORMATION;
  matchSize();
  std::string prefix = param("topic_prefix").as_string();
  rclcpp::SubscriptionOptions options; options.callback_group = callback_group_;
  // Reliable transport is REQUIRED for the multi-megabyte observation
  // messages (pair-1-on-qosfix, October 2026): best-effort drops whole
  // clouds wholesale without fragment retransmits (>90% loss in the
  // quiescent phase). Depth 8 keeps the digest triple join robust.
  auto qos = rclcpp::QoS(8).reliable();
  mask_sub_ = node->create_subscription<sensor_msgs::msg::Image>(prefix + "/mask", qos,
    [this](sensor_msgs::msg::Image::ConstSharedPtr msg) {receiveMask(msg);}, options);
  cloud_sub_ = node->create_subscription<sensor_msgs::msg::PointCloud2>(prefix + "/points", qos,
    [this](sensor_msgs::msg::PointCloud2::ConstSharedPtr msg) {receiveCloud(msg);}, options);
  timing_sub_ = node->create_subscription<std_msgs::msg::String>(prefix + "/timing", qos,
    [this](std_msgs::msg::String::ConstSharedPtr msg) {receiveTiming(msg->data);}, options);
  labels_sub_ = node->create_subscription<std_msgs::msg::String>(prefix + "/label_info",
    rclcpp::QoS(1).reliable().transient_local(),
    [this](std_msgs::msg::String::ConstSharedPtr msg) {receiveLabels(msg->data);}, options);
  activate();
}

void SemanticLayer::clearLocked()
{
  cells_.clear(); pending_.clear(); resetMaps(); ++epoch_;
  barrier_wall_ = wallNow() + uncertainty_ns_;
  last_stamp_ = last_wall_ = -1; stream_epoch_.clear(); last_request_.clear(); raster_request_.clear();
  last_applied_ = nullptr; current_ = false; reason_ = "epoch_cleared";
}
void SemanticLayer::matchSize()
{
  std::lock_guard<std::recursive_mutex> lock(state_mutex_);
  CostmapLayer::matchSize(); anchor_x_ = getOriginX(); anchor_y_ = getOriginY(); clearLocked();
}
void SemanticLayer::reset()
{std::lock_guard<std::recursive_mutex> lock(state_mutex_); clearLocked();}
void SemanticLayer::activate()
{std::lock_guard<std::recursive_mutex> lock(state_mutex_); clearLocked(); active_ = true;}
void SemanticLayer::deactivate()
{std::lock_guard<std::recursive_mutex> lock(state_mutex_); active_ = false; clearLocked();}
void SemanticLayer::clockCheck()
{
  const auto now = simNow();
  if (last_sim_ >= 0 && now < last_sim_) {clearLocked(); reason_ = "clock_rollback";}
  last_sim_ = now;
}
void SemanticLayer::boundPending()
{
  while (pending_.size() > 8) {pending_.erase(pending_.begin()); ++evicted_;}
}
void SemanticLayer::receiveLabels(const std::string & text)
{
  std::lock_guard<std::recursive_mutex> lock(state_mutex_);
  bool valid = false;
  std::string why;
  try {
    auto j = Json::parse(text);
    if (j.at("policy") != "avoid-target/v1") {why = "policy";}
    else if (j.at("generation") != 1) {why = "generation";}
    else if (j.at("labels") != Json({{"0", "unobserved"}, {"1", "traversable"}, {"2", "avoid_target"}})) {why = "labels_map";}
    else if (j.at("active_labels") != Json::array({0, 2})) {why = "active_labels";}
    else {valid = true;}
  } catch (const std::exception & e) {why = std::string("exception:") + e.what();}
  if (!valid) {clearLocked(); reason_ = "invalid_labels";}
  labels_valid_ = valid;
  // Rate-limited arrival/validation diagnostics: distinguishes "never
  // arrived" from "arrived but invalid" from logs alone (Phase 6 smoke
  // attempts 2-4). Admission policy is unchanged.
  const auto log_wall = wallNow();
  if (log_wall - last_label_log_wall_ns_ >= 5000000000LL) {
    if (auto node = node_.lock()) {
      RCLCPP_WARN(node->get_logger(),
        "semantic label_info received bytes=%zu valid=%d why=%s",
        text.size(), labels_valid_ ? 1 : 0, why.c_str());
    }
    last_label_log_wall_ns_ = log_wall;
  }
}
void SemanticLayer::receiveMask(sensor_msgs::msg::Image::ConstSharedPtr msg)
{
  std::lock_guard<std::recursive_mutex> lock(state_mutex_); clockCheck();
  if (!active_ || !enabled_) {return;}
  if (msg->data.size() > 307200 || msg->width == 0 || msg->height == 0) {++rejected_; return;}
  auto stamp = stampNs(msg->header); pending_[stamp].mask = msg; boundPending(); attempt(stamp);
}
void SemanticLayer::receiveCloud(sensor_msgs::msg::PointCloud2::ConstSharedPtr msg)
{
  std::lock_guard<std::recursive_mutex> lock(state_mutex_); clockCheck();
  if (!active_ || !enabled_) {return;}
  if (msg->data.size() > 307200 * 12) {++rejected_; return;}
  auto stamp = stampNs(msg->header); pending_[stamp].cloud = msg; boundPending(); attempt(stamp);
}
void SemanticLayer::receiveTiming(const std::string & text)
{
  std::lock_guard<std::recursive_mutex> lock(state_mutex_); clockCheck();
  if (!active_ || !enabled_) {return;}
  try {
    if (text.size() > 16384) {throw std::invalid_argument("oversize timing");}
    auto timing = Json::parse(text);
    auto stamp = timing.at("capture").at("stamp_ns").get<int64_t>();
    pending_[stamp].timing = timing; boundPending(); attempt(stamp);
  } catch (const std::exception & e) {++rejected_; reason_ = e.what();}
}

void SemanticLayer::attempt(int64_t stamp)
{
  // Per-observation segment timing (pair-1-on-tfwitness follow-up): the
  // on-arm controller cycle blocked ~160 ms at motion start and the chain
  // correctly failed command_expired; the suspects are this callback's
  // digest/projection work under state_mutex_ and its contention with
  // updateBounds on the costmap update thread. Diagnostics only — no
  // behavior change. At ~7 results/s every observation is logged.
  const auto attempt_start = std::chrono::steady_clock::now();
  double digest_ms = 0.0, tf_ms = 0.0, project_ms = 0.0;
  auto it = pending_.find(stamp);
  if (it == pending_.end() || !it->second.mask || !it->second.cloud || it->second.timing.is_null()) {return;}
  auto item = std::move(it->second); pending_.erase(it);
  int64_t capture_wall = 0;
  try {
    const auto & m = *item.mask; const auto & c = *item.cloud; const auto & t = item.timing;
    capture_wall = t.at("capture_wall_ns").get<int64_t>();
    const auto wall = capture_wall;
    const auto now = wallNow(); const auto sim = simNow();
    const auto & id = t.at("identity");
    const auto epoch = id.at("epoch").get<std::string>();
    const auto request = id.at("request_id").get<std::string>();
    // Split rejection reasons: the aggregate "stale_or_wrong_identity"
    // cannot be diagnosed from logs (Phase 6 smoke attempts 2/3 rejected
    // every observation). Same conditions, same order, same fail-closed
    // policy — only the reported reason is specific.
    const char * detail = nullptr;
    if (!labels_valid_) {detail = "labels_invalid";}
    else if (wall <= barrier_wall_) {detail = "wall_before_barrier";}
    else if (wall <= last_wall_) {detail = "wall_not_increasing";}
    else if (now - wall + uncertainty_ns_ > max_age_ns_) {detail = "wall_age";}
    else if (wall > now + uncertainty_ns_) {detail = "wall_future";}
    else if (sim < stamp) {detail = "sim_behind_capture";}
    else if (sim - stamp > max_age_ns_) {detail = "sim_age";}
    else if (id.at("robot") != "robot_1") {detail = "robot_identity";}
    else if (id.at("stream") != "camera/color") {detail = "stream_identity";}
    else if (id.at("generation") != 1) {detail = "generation_identity";}
    else if (epoch.empty()) {detail = "epoch_empty";}
    else if (request.empty()) {detail = "request_empty";}
    else if (request == last_request_) {detail = "duplicate_request";}
    else if (epoch == stream_epoch_ && stamp <= last_stamp_) {detail = "stale_stamp";}
    if (detail) {throw std::invalid_argument(detail);}
    if (m.header.frame_id != frame_ || c.header.frame_id != frame_ ||
      t.at("capture").at("frame_id") != frame_ || m.encoding != "mono8" || m.is_bigendian ||
      m.width != c.width || m.height != c.height || m.step != m.width ||
      m.data.size() != size_t(m.width) * m.height || c.is_bigendian ||
      c.point_step != 12 || c.row_step != c.width * 12 ||
      c.data.size() != size_t(c.row_step) * c.height || c.fields.size() != 3)
    {throw std::invalid_argument("invalid_layout");}
    for (size_t i = 0; i < 3; ++i) {
      if (c.fields[i].name != std::vector<std::string>{"x", "y", "z"}[i] ||
        c.fields[i].offset != 4 * i || c.fields[i].datatype != 7 || c.fields[i].count != 1)
      {throw std::invalid_argument("invalid_xyz_fields");}
    }
    // Header timestamps alone are ambiguous after a simulation reset. Digests
    // bind all three DDS messages to the same inference publication.
    const auto digest_start = std::chrono::steady_clock::now();
    const bool digest_ok = t.at("mask_sha256") == digest(m.data) && t.at("cloud_sha256") == digest(c.data);
    digest_ms = std::chrono::duration<double, std::milli>(
      std::chrono::steady_clock::now() - digest_start).count();
    if (!digest_ok)
    {throw std::invalid_argument("payload_digest_mismatch");}
    const auto tf_start = std::chrono::steady_clock::now();
    const auto transform = tf_->lookupTransform(layered_costmap_->getGlobalFrameID(), frame_,
      rclcpp::Time(m.header.stamp), rclcpp::Duration::from_seconds(0));
    tf_ms = std::chrono::duration<double, std::milli>(
      std::chrono::steady_clock::now() - tf_start).count();
    tf2::Transform pose; tf2::fromMsg(transform.transform, pose);
    std::map<std::pair<int, int>, Cell> projected;
    const auto project_start = std::chrono::steady_clock::now();
    for (size_t i = 0; i < m.data.size(); ++i) {
      if (m.data[i] != 0 && m.data[i] != 2) {throw std::invalid_argument("unmapped_label");}
      if (m.data[i] == 0) {continue;}
      float xyz[3]; std::memcpy(xyz, &c.data[i * 12], 12);
      if (!std::isfinite(xyz[0]) || !std::isfinite(xyz[1]) || !std::isfinite(xyz[2]) ||
        xyz[2] <= 0 || xyz[0]*xyz[0] + xyz[1]*xyz[1] + xyz[2]*xyz[2] > max_range_*max_range_)
      {continue;}
      auto point = pose * tf2::Vector3(xyz[0], xyz[1], xyz[2]);
      if (!std::isfinite(point.x()) || !std::isfinite(point.y()) || !std::isfinite(point.z()) ||
        point.z() < min_height_ || point.z() > max_height_) {continue;}
      unsigned int x, y;
      if (!worldToMap(point.x(), point.y(), x, y)) {continue;}
      projected[{int(std::floor((point.x()-anchor_x_)/getResolution())), int(std::floor((point.y()-anchor_y_)/getResolution()))}] = {stamp, wall};
    }
    project_ms = std::chrono::duration<double, std::milli>(
      std::chrono::steady_clock::now() - project_start).count();
    // New producer epoch clears old semantic observations, but may only enter
    // through the strictly newer wall-capture gate above.
    if (!stream_epoch_.empty() && epoch != stream_epoch_) {cells_.clear(); pending_.clear();}
    expire();
    if (cells_.size() + projected.size() > 65536) {throw std::invalid_argument("cell_capacity");}
    for (const auto & cell : projected) {cells_[cell.first] = cell.second;}
    stream_epoch_ = epoch; last_stamp_ = stamp; last_wall_ = wall; last_request_ = request;
    ++accepted_; reason_ = "accepted"; current_ = true;
    last_applied_ = {{"request_id", request}, {"capture_wall_ns", wall}, {"stamp_ns", stamp},
      {"projected_cells", projected.size()}, {"received_wall_ns", wallNow()}, {"layer_epoch", epoch_}};
    {
      const auto total_ms = std::chrono::duration<double, std::milli>(
        std::chrono::steady_clock::now() - attempt_start).count();
      if (auto node = node_.lock()) {
        RCLCPP_INFO(node->get_logger(),
          "semantic attempt timing stamp_ns=%ld total_ms=%.2f digest_ms=%.2f tf_ms=%.2f project_ms=%.2f projected=%zu cells=%zu",
          static_cast<long>(stamp), total_ms, digest_ms, tf_ms, project_ms,
          projected.size(), cells_.size());
      }
    }
    const auto log_wall = wallNow();
    if (log_wall - last_runtime_log_wall_ns_ >= 5000000000LL) {
      if (auto node = node_.lock()) {
        RCLCPP_INFO(node->get_logger(),
          "semantic observation accepted=%lu rejected=%lu projected_cells=%zu sim_age_ms=%.2f wall_age_ms=%.2f",
          static_cast<unsigned long>(accepted_), static_cast<unsigned long>(rejected_),
          projected.size(), (sim - stamp) / 1e6, (log_wall - wall + uncertainty_ns_) / 1e6);
      }
      last_runtime_log_wall_ns_ = log_wall;
    }
  } catch (const std::exception & e) {++rejected_; reason_ = e.what();}
  if (reason_ != "accepted") {
    const auto log_wall = wallNow();
    if (log_wall - last_runtime_log_wall_ns_ >= 5000000000LL) {
      if (auto node = node_.lock()) {
        RCLCPP_WARN(node->get_logger(),
          "semantic observation rejected=%lu accepted=%lu reason=%s pending=%zu "
          "wall_age_ms=%.2f sim_age_ms=%.2f labels_valid=%d",
          static_cast<unsigned long>(rejected_), static_cast<unsigned long>(accepted_),
          reason_.c_str(), pending_.size(),
          (capture_wall ? (log_wall - capture_wall) / 1e6 : -1.0),
          (simNow() - stamp) / 1e6, labels_valid_ ? 1 : 0);
      }
      last_runtime_log_wall_ns_ = log_wall;
    }
  }
}
void SemanticLayer::expire()
{
  const auto sim = simNow(); const auto wall = wallNow();
  for (auto it = cells_.begin(); it != cells_.end();) {
    if (sim - it->second.sim_ns >= ttl_ns_ || wall - it->second.wall_ns + uncertainty_ns_ >= ttl_ns_)
    {it = cells_.erase(it);} else {++it;}
  }
  for (auto it = pending_.begin(); it != pending_.end();) {
    if (sim < it->first || sim - it->first > max_age_ns_) {it = pending_.erase(it); ++evicted_;}
    else {++it;}
  }
  current_ = active_ && labels_valid_ && last_wall_ > 0 &&
    wall - last_wall_ + uncertainty_ns_ <= max_age_ns_ && sim >= last_stamp_ && sim - last_stamp_ <= max_age_ns_;
}
void SemanticLayer::updateBounds(double rx, double ry, double, double * minx, double * miny, double * maxx, double * maxy)
{
  // Lock-wait and duration timing (pair-1-on-tfwitness follow-up): the
  // costmap update thread contends state_mutex_ with the observation
  // callbacks' digest/projection work; the controller's cycle reads the
  // costmap under the master map mutex, so a slow updateBounds delays
  // control cycles. Diagnostics only — no behavior change.
  const auto bounds_start = std::chrono::steady_clock::now();
  const auto lock_start = std::chrono::steady_clock::now();
  std::lock_guard<std::recursive_mutex> lock(state_mutex_);
  const double lock_wait_ms = std::chrono::duration<double, std::milli>(
    std::chrono::steady_clock::now() - lock_start).count();
  clockCheck();
  if (layered_costmap_->isRolling()) {updateOrigin(rx - getSizeInMetersX()/2, ry - getSizeInMetersY()/2);}
  // Rebuild the entire bounded raster, and request its entire master window.
  // This includes cells that disappeared, even when inactive or expired.
  resetMaps(); expire();
  *minx = std::min(*minx, getOriginX()); *miny = std::min(*miny, getOriginY());
  *maxx = std::max(*maxx, getOriginX() + getSizeInMetersX() + getResolution());
  *maxy = std::max(*maxy, getOriginY() + getSizeInMetersY() + getResolution());
  if (!active_ || !enabled_) {return;}
  raster_request_ = last_request_;
  for (auto it = cells_.begin(); it != cells_.end();) {
    unsigned int x, y;
    if (!worldToMap(anchor_x_ + (it->first.first + 0.5)*getResolution(), anchor_y_ + (it->first.second + 0.5)*getResolution(), x, y))
    {it = cells_.erase(it); continue;}
    setCost(x, y, target_cost_); ++it;
  }
  const auto bounds_total_ms = std::chrono::duration<double, std::milli>(
    std::chrono::steady_clock::now() - bounds_start).count();
  if (bounds_total_ms >= 15.0 || lock_wait_ms >= 5.0) {
    if (auto node = node_.lock()) {
      RCLCPP_WARN(node->get_logger(),
        "semantic updateBounds slow total_ms=%.2f lock_wait_ms=%.2f cells=%zu",
        bounds_total_ms, lock_wait_ms, cells_.size());
    }
  }
}
void SemanticLayer::updateCosts(nav2_costmap_2d::Costmap2D & master, int minx, int miny, int maxx, int maxy)
{
  std::lock_guard<std::recursive_mutex> lock(state_mutex_);
  if (!active_ || !enabled_) {return;}
  size_t semantic_cells = 0, merged_cells = 0, unknown_master_cells = 0;
  for (int y = miny; y < maxy; ++y) {
    for (int x = minx; x < maxx; ++x) {
      auto semantic = getCost(x, y), geometric = master.getCost(x, y);
      if (semantic != NO_INFORMATION) {++semantic_cells;}
      // Conservative maximum: semantic labels never turn UNKNOWN into known
      // space and never reduce lethal/static/geometric costs.
      if (semantic != NO_INFORMATION && geometric != NO_INFORMATION)
      {master.setCost(x, y, std::max(semantic, geometric)); ++merged_cells;}
      else if (semantic != NO_INFORMATION && geometric == NO_INFORMATION)
      {++unknown_master_cells;}
    }
  }
  const auto log_wall = wallNow();
  if (log_wall - last_cost_log_wall_ns_ >= 5000000000LL) {
    if (auto node = node_.lock()) {
      RCLCPP_INFO(node->get_logger(),
        "semantic cost merge marked=%zu merged=%zu master_unknown=%zu stored_cells=%zu window=[%d,%d,%d,%d]",
        semantic_cells, merged_cells, unknown_master_cells, cells_.size(), minx, miny, maxx, maxy);
    }
    last_cost_log_wall_ns_ = log_wall;
  }
  if (!last_applied_.is_null() && last_applied_["request_id"] == raster_request_ &&
    !last_applied_.contains("costmap_wall_ns")) {
    last_applied_["costmap_wall_ns"] = wallNow();
    last_applied_["capture_to_costmap_upper_ms"] =
      (wallNow() - last_wall_ + uncertainty_ns_) / 1e6;
  }
}
Json SemanticLayer::diagnostics()
{
  std::lock_guard<std::recursive_mutex> lock(state_mutex_);
  return {{"accepted", accepted_}, {"rejected", rejected_}, {"evicted", evicted_},
    {"pending", pending_.size()}, {"cells", cells_.size()}, {"epoch", epoch_},
    {"active", active_}, {"current", current_}, {"reason", reason_}, {"last", last_applied_}};
}
}  // namespace demo_semantic_costmap
PLUGINLIB_EXPORT_CLASS(demo_semantic_costmap::SemanticLayer, nav2_costmap_2d::Layer)
