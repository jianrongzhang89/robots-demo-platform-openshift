// Diagnostic-only capture tracing for the pinned gz-sensors 8.2.2 RGB-D sensor.
// Does not change sensor data, ROS timestamps, rendering, or update frequency.
#pragma once
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <gz/msgs/stringmsg.pb.h>
#include <gz/transport/Node.hh>

class SemanticCaptureTrace
{
  using Nano = std::chrono::nanoseconds;
  static int64_t Wall()
  {
    return std::chrono::duration_cast<Nano>(
        std::chrono::system_clock::now().time_since_epoch()).count();
  }
  static int64_t Steady()
  {
    return std::chrono::duration_cast<Nano>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
  }
  static std::string Epoch()
  {
    std::ifstream file("/proc/sys/kernel/random/uuid");
    std::string result;
    std::getline(file, result);
    if (result.empty()) throw std::runtime_error("capture epoch unavailable");
    return result;
  }
  gz::transport::Node node;
  gz::transport::Node::Publisher publisher;
  std::string epoch = Epoch();
  int64_t lastStamp = -1, sequence = 0;
  int64_t wallStart = 0, steadyStart = 0, wallRendered = 0, steadyRendered = 0;
  public: explicit SemanticCaptureTrace(const std::string &topic)
  {
    publisher = node.Advertise<gz::msgs::StringMsg>(topic + "/capture_trace");
  }
  public: void Begin(const std::chrono::steady_clock::duration &stamp)
  {
    const auto ns = std::chrono::duration_cast<Nano>(stamp).count();
    if (ns <= lastStamp) { epoch = Epoch(); sequence = 0; }
    lastStamp = ns;
    ++sequence;
    wallStart = Wall();
    steadyStart = Steady();
  }
  public: void Rendered()
  {
    wallRendered = Wall();
    steadyRendered = Steady();
  }
  public: void End()
  {
    const auto wallEnd = Wall();
    const auto steadyEnd = Steady();
    std::ostringstream json;
    json << "{\"schema\":\"semantic-capture/v1\",\"source_epoch\":\"" << epoch
         << "\",\"sequence\":" << sequence << ",\"stamp_ns\":" << lastStamp
         << ",\"capture_wall_ns\":" << wallStart
         << ",\"rendered_wall_ns\":" << wallRendered
         << ",\"source_publish_wall_ns\":" << wallEnd
         << ",\"render_duration_ns\":" << steadyRendered - steadyStart
         << ",\"source_duration_ns\":" << steadyEnd - steadyStart << "}";
    gz::msgs::StringMsg msg;
    msg.set_data(json.str());
    publisher.Publish(msg);
  }
};
