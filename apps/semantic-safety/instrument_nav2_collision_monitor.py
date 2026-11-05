#!/usr/bin/env python3
"""Add opt-in CM timing-only instrumentation to the pinned Nav2 source tree."""
from pathlib import Path

ROOT = Path("/opt/nav2-smoother-src/nav2_collision_monitor/src")


def replace_once(path: Path, old: str, new: str) -> None:
    source = path.read_text()
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"expected one instrumentation anchor in {path.name}, found {count}")
    path.write_text(source.replace(old, new, 1))


node = ROOT / "collision_monitor_node.cpp"
replace_once(node, "#include <functional>\n", "#include <functional>\n#include <chrono>\n")
replace_once(
    node,
    """void CollisionMonitor::cmdVelInCallbackStamped(geometry_msgs::msg::TwistStamped::SharedPtr msg)
{
  // If message contains NaN or Inf, ignore
""",
    """void CollisionMonitor::cmdVelInCallbackStamped(geometry_msgs::msg::TwistStamped::SharedPtr msg)
{
  using SteadyClock = std::chrono::steady_clock;
  const auto callback_start = SteadyClock::now();
  static SteadyClock::time_point previous_callback{};
  static long long previous_message_stamp_ns = 0;
  const auto steady_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
    callback_start.time_since_epoch()).count();
  const auto wall_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
    std::chrono::system_clock::now().time_since_epoch()).count();
  const auto message_stamp_ns = static_cast<long long>(msg->header.stamp.sec) * 1000000000LL +
    static_cast<long long>(msg->header.stamp.nanosec);
  if (previous_callback.time_since_epoch().count() != 0) {
    const auto gap_us = std::chrono::duration_cast<std::chrono::microseconds>(
      callback_start - previous_callback).count();
    if (gap_us >= 20000) {
      const auto stamp_delta_us = previous_message_stamp_ns == 0 ? -1 :
        (message_stamp_ns - previous_message_stamp_ns) / 1000;
      RCLCPP_WARN(
        get_logger(),
        "CM_DIAG kind=callback_gap gap_us=%lld stamp_delta_us=%lld stamp=%u.%09u steady_ns=%lld wall_ns=%lld",
        static_cast<long long>(gap_us), stamp_delta_us,
        static_cast<unsigned int>(msg->header.stamp.sec), msg->header.stamp.nanosec,
        static_cast<long long>(steady_ns), static_cast<long long>(wall_ns));
    }
  }
  previous_callback = callback_start;
  previous_message_stamp_ns = message_stamp_ns;

  // If message contains NaN or Inf, ignore
""")
replace_once(
    node,
    """  process({msg->twist.linear.x, msg->twist.linear.y, msg->twist.angular.z}, msg->header);
}
""",
    """  process({msg->twist.linear.x, msg->twist.linear.y, msg->twist.angular.z}, msg->header);
  const auto process_us = std::chrono::duration_cast<std::chrono::microseconds>(
    SteadyClock::now() - callback_start).count();
  if (process_us >= 25000) {
    RCLCPP_WARN(
      get_logger(),
      "CM_DIAG kind=callback_process duration_us=%lld stamp=%u.%09u steady_ns=%lld wall_ns=%lld",
      static_cast<long long>(process_us), static_cast<unsigned int>(msg->header.stamp.sec),
      msg->header.stamp.nanosec,
      static_cast<long long>(steady_ns), static_cast<long long>(wall_ns));
  }
}
""")
replace_once(
    node,
    """    if (source->getEnabled()) {
      if (!source->getData(curr_time, iter.first->second) &&
        source->getSourceTimeout().seconds() != 0.0)
""",
    """    if (source->getEnabled()) {
      const auto source_start = std::chrono::steady_clock::now();
      const auto source_steady_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
        source_start.time_since_epoch()).count();
      const auto source_wall_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
      const bool source_ok = source->getData(curr_time, iter.first->second);
      const auto source_us = std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now() - source_start).count();
      if (source_us >= 25000) {
        RCLCPP_WARN(
          get_logger(),
          "CM_DIAG kind=source_data source=%s duration_us=%lld points=%zu ok=%d steady_ns=%lld wall_ns=%lld",
          source->getSourceName().c_str(), static_cast<long long>(source_us),
          iter.first->second.size(), source_ok ? 1 : 0,
          static_cast<long long>(source_steady_ns), static_cast<long long>(source_wall_ns));
      }
      if (!source_ok &&
        source->getSourceTimeout().seconds() != 0.0)
""")

source = ROOT / "source.cpp"
replace_once(
    source,
    "#include <exception>\n",
    """#include <exception>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <string>
#include <sys/syscall.h>
#include <thread>
#include <time.h>
#include <unistd.h>

namespace
{
long long currentThreadCpuNs()
{
  timespec value{};
  if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &value) != 0) {
    return -1;
  }
  return static_cast<long long>(value.tv_sec) * 1000000000LL + value.tv_nsec;
}

struct ThreadSchedstat
{
  unsigned long long runtime_ns{0};
  unsigned long long runqueue_ns{0};
  unsigned long long slices{0};
  bool valid{false};
};

ThreadSchedstat currentThreadSchedstat()
{
  const auto tid = static_cast<long>(syscall(SYS_gettid));
  std::ifstream input("/proc/self/task/" + std::to_string(tid) + "/schedstat");
  ThreadSchedstat result;
  result.valid = static_cast<bool>(input >> result.runtime_ns >> result.runqueue_ns >> result.slices);
  return result;
}
}  // namespace
"""
)
replace_once(
    source,
    """  if (base_shift_correction_) {
    if (
      !nav2_util::getTransform(
        data_header.frame_id, data_header.stamp,
        base_frame_id_, curr_time, global_frame_id_,
        transform_tolerance_, tf_buffer_, tf_transform))
    {
      return false;
    }
  } else {
    if (
      !nav2_util::getTransform(
        data_header.frame_id, base_frame_id_,
        transform_tolerance_, tf_buffer_, tf_transform))
    {
      return false;
    }
  }
  return true;
""",
    """  using SteadyClock = std::chrono::steady_clock;
  const auto cpu_start_ns = currentThreadCpuNs();
  const auto sched_start = currentThreadSchedstat();
  const auto tf_start = SteadyClock::now();
  const auto steady_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
    tf_start.time_since_epoch()).count();
  const auto wall_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
    std::chrono::system_clock::now().time_since_epoch()).count();
  const char * edge_probe_env = std::getenv("PHASE5_TF_EDGE_PROBE");
  const bool edge_probe_enabled = base_shift_correction_ && edge_probe_env != nullptr &&
    std::string(edge_probe_env) == "1";
  const char * fast_poll_env = std::getenv("PHASE5_TF2_POLL_1MS");
  const bool fast_poll_enabled = fast_poll_env != nullptr && std::string(fast_poll_env) == "1";
  std::atomic<bool> stop_edge_probe{false};
  std::atomic<long long> source_edge_ready_us{-1};
  std::atomic<long long> target_edge_ready_us{-1};
  std::thread edge_probe_thread;
  if (edge_probe_enabled) {
    edge_probe_thread = std::thread([&]() {
      while (!stop_edge_probe.load(std::memory_order_relaxed)) {
        const auto elapsed_us = std::chrono::duration_cast<std::chrono::microseconds>(
          SteadyClock::now() - tf_start).count();
        if (source_edge_ready_us.load(std::memory_order_relaxed) < 0 &&
          tf_buffer_->canTransform(
            global_frame_id_, data_header.frame_id, rclcpp::Time(data_header.stamp)))
        {
          source_edge_ready_us.store(elapsed_us, std::memory_order_relaxed);
        }
        if (target_edge_ready_us.load(std::memory_order_relaxed) < 0 &&
          tf_buffer_->canTransform(global_frame_id_, base_frame_id_, curr_time))
        {
          target_edge_ready_us.store(elapsed_us, std::memory_order_relaxed);
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
      }
    });
  }
  bool transform_ok = false;
  if (base_shift_correction_) {
    transform_ok = nav2_util::getTransform(
      data_header.frame_id, data_header.stamp,
      base_frame_id_, curr_time, global_frame_id_,
      transform_tolerance_, tf_buffer_, tf_transform);
  } else {
    transform_ok = nav2_util::getTransform(
      data_header.frame_id, base_frame_id_,
      transform_tolerance_, tf_buffer_, tf_transform);
  }
  const auto tf_end = SteadyClock::now();
  stop_edge_probe.store(true, std::memory_order_relaxed);
  if (edge_probe_thread.joinable()) {
    edge_probe_thread.join();
  }
  const bool source_edge_ready_at_end = edge_probe_enabled && tf_buffer_->canTransform(
    global_frame_id_, data_header.frame_id, rclcpp::Time(data_header.stamp));
  const bool target_edge_ready_at_end = edge_probe_enabled &&
    tf_buffer_->canTransform(global_frame_id_, base_frame_id_, curr_time);
  const auto cpu_end_ns = currentThreadCpuNs();
  const auto sched_end = currentThreadSchedstat();
  const auto tf_us = std::chrono::duration_cast<std::chrono::microseconds>(tf_end - tf_start).count();
  const auto thread_cpu_us = cpu_start_ns >= 0 && cpu_end_ns >= cpu_start_ns ?
    (cpu_end_ns - cpu_start_ns) / 1000 : -1;
  const bool sched_valid = sched_start.valid && sched_end.valid &&
    sched_end.runtime_ns >= sched_start.runtime_ns && sched_end.runqueue_ns >= sched_start.runqueue_ns;
  const auto sched_run_us = sched_valid ?
    static_cast<long long>((sched_end.runtime_ns - sched_start.runtime_ns) / 1000) : -1;
  const auto runqueue_wait_us = sched_valid ?
    static_cast<long long>((sched_end.runqueue_ns - sched_start.runqueue_ns) / 1000) : -1;
  const auto slices = sched_valid ?
    static_cast<long long>(sched_end.slices - sched_start.slices) : -1;
  const auto offcpu_unattributed_us = sched_valid && thread_cpu_us >= 0 ?
    tf_us - thread_cpu_us - runqueue_wait_us : -1;
  long long log_threshold_us = edge_probe_enabled ? (fast_poll_enabled ? 1000 : 8000) : 25000;
  const char * configured_log_threshold = std::getenv("PHASE5_TF_LOG_THRESHOLD_US");
  if (edge_probe_enabled && configured_log_threshold != nullptr) {
    const std::string threshold_value(configured_log_threshold);
    if (threshold_value == "1000") {
      log_threshold_us = 1000;
    } else if (threshold_value == "8000") {
      log_threshold_us = 8000;
    }
  }
  if (tf_us >= log_threshold_us) {
    RCLCPP_WARN(
      logger_,
      "CM_DIAG kind=tf source=%s frame=%s target=%s fixed=%s source_stamp=%u.%09u target_stamp_ns=%lld tolerance_ns=%lld duration_us=%lld thread_cpu_us=%lld sched_run_us=%lld runqueue_wait_us=%lld offcpu_unattributed_us=%lld slices=%lld schedstat_ok=%d ok=%d edge_probe=%d source_edge_ready_us=%lld target_edge_ready_us=%lld source_edge_at_end=%d target_edge_at_end=%d steady_ns=%lld wall_ns=%lld",
      source_name_.c_str(), data_header.frame_id.c_str(),
      base_frame_id_.c_str(), global_frame_id_.c_str(),
      static_cast<unsigned int>(data_header.stamp.sec), data_header.stamp.nanosec,
      static_cast<long long>(curr_time.nanoseconds()),
      static_cast<long long>(transform_tolerance_.count()),
      static_cast<long long>(tf_us), thread_cpu_us, sched_run_us, runqueue_wait_us,
      offcpu_unattributed_us, slices, sched_valid ? 1 : 0, transform_ok ? 1 : 0,
      edge_probe_enabled ? 1 : 0,
      source_edge_ready_us.load(std::memory_order_relaxed),
      target_edge_ready_us.load(std::memory_order_relaxed),
      source_edge_ready_at_end ? 1 : 0, target_edge_ready_at_end ? 1 : 0,
      static_cast<long long>(steady_ns), static_cast<long long>(wall_ns));
  }
  return transform_ok;
""")
