#pragma once

#include <map>
#include <mutex>
#include <string>
#include <vector>
#include <nlohmann/json.hpp>
#include <nav2_costmap_2d/costmap_layer.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <std_msgs/msg/string.hpp>

namespace demo_semantic_costmap
{
// This layer intentionally supports one fixed camera/policy, not arbitrary
// ontology changes or confidence accumulation. All mutation is mutex guarded.
class SemanticLayer : public nav2_costmap_2d::CostmapLayer
{
public:
  void onInitialize() override;
  void matchSize() override;
  void reset() override;
  void activate() override;
  void deactivate() override;
  bool isClearable() override {return false;}  // Partial clear cannot establish an epoch.
  void updateBounds(double, double, double, double *, double *, double *, double *) override;
  void updateCosts(nav2_costmap_2d::Costmap2D &, int, int, int, int) override;

  // Shared by ROS callbacks and deterministic integration tests.
  void receiveMask(sensor_msgs::msg::Image::ConstSharedPtr);
  void receiveCloud(sensor_msgs::msg::PointCloud2::ConstSharedPtr);
  void receiveTiming(const std::string &);
  void receiveLabels(const std::string &);
  nlohmann::json diagnostics();
  static std::string digest(const std::vector<uint8_t> &);

protected:
  // Virtual clocks are overridden only by the test harness. Runtime uses the
  // real node ROS clock and system wall clock; monotonic time never crosses hosts.
  virtual int64_t wallNow() const;
  virtual int64_t simNow() const;

private:
  struct Pending {
    sensor_msgs::msg::Image::ConstSharedPtr mask;
    sensor_msgs::msg::PointCloud2::ConstSharedPtr cloud;
    nlohmann::json timing;
  };
  struct Cell {int64_t sim_ns; int64_t wall_ns;};
  void clearLocked();
  void clockCheck();
  void attempt(int64_t stamp);
  void boundPending();
  void expire();
  std::recursive_mutex state_mutex_;
  std::map<int64_t, Pending> pending_;
  std::map<std::pair<int, int>, Cell> cells_;
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr mask_sub_;
  rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr cloud_sub_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr timing_sub_, labels_sub_;
  bool active_{false}, labels_valid_{false};
  int64_t barrier_wall_{0}, last_sim_{-1}, last_stamp_{-1}, last_wall_{-1};
  int64_t ttl_ns_{1000000000}, max_age_ns_{500000000}, uncertainty_ns_{2000000};
  int64_t last_runtime_log_wall_ns_{0};
  int64_t last_cost_log_wall_ns_{0};
  int64_t last_label_log_wall_ns_{0};
  uint64_t epoch_{0}, accepted_{0}, rejected_{0}, evicted_{0};
  std::string stream_epoch_, last_request_, reason_{"not_ready"};
  std::string raster_request_;
  std::string frame_{"camera_color_optical_frame"};
  double min_height_{-0.15}, max_height_{0.15}, max_range_{5.0};
  double anchor_x_{0}, anchor_y_{0};
  unsigned char target_cost_{200};
  nlohmann::json last_applied_;
};
}  // namespace demo_semantic_costmap
