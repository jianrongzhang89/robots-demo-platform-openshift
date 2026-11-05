// Read-only command provenance observer. NEVER publishes Twist or actuator leases.
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>
#include <dds/dds.h>
#include <nlohmann/json.hpp>
#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/twist_stamped.hpp>
#include <std_msgs/msg/string.hpp>

class CommandObserver : public rclcpp::Node {
  using Twist = geometry_msgs::msg::TwistStamped;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr output;
  std::vector<rclcpp::Subscription<Twist>::SharedPtr> inputs;
  dds_entity_t discovery_participant{0};
  dds_entity_t publication_reader{0};

  std::vector<unsigned> resolve_publisher(const rmw_gid_t & sample_gid) const {
    // rmw_cyclonedds 2.2.4 copies dds_sample_info_t::publication_handle into
    // publisher_gid, rather than the discovered 16-byte endpoint GUID. Resolve
    // that local handle through Cyclone's DCPSPublication built-in topic.
    if (publication_reader <= 0 || sizeof(dds_instance_handle_t) > sizeof(sample_gid.data)) {
      return {};
    }
    dds_instance_handle_t handle{};
    std::memcpy(&handle, sample_gid.data, sizeof(handle));
    if (handle == DDS_HANDLE_NIL) {
      return {};
    }
    void * sample = nullptr;
    dds_sample_info_t info{};
    const auto count = dds_read_instance(publication_reader, &sample, &info, 1, 1, handle);
    if (count != 1 || !info.valid_data || sample == nullptr) {
      if (count > 0) {
        dds_return_loan(publication_reader, &sample, count);
      }
      return {};
    }
    const auto * endpoint = static_cast<const dds_builtintopic_endpoint_t *>(sample);
    std::vector<unsigned> guid(endpoint->key.v, endpoint->key.v + sizeof(endpoint->key.v));
    dds_return_loan(publication_reader, &sample, count);
    return guid;
  }

 public:
  CommandObserver() : Node("phase5_command_observer") {
    const char *domain=std::getenv("ROS_DOMAIN_ID");
    const char *dds=std::getenv("CYCLONEDDS_URI");
    if (!domain || std::string(domain)!="85" || !dds || std::string(dds).find("phase5")==std::string::npos)
      throw std::runtime_error("private Phase 5 observer only");
    discovery_participant=dds_create_participant(85,nullptr,nullptr);
    if (discovery_participant<0) throw std::runtime_error("failed to create private Cyclone discovery participant");
    publication_reader=dds_create_reader(discovery_participant,DDS_BUILTIN_TOPIC_DCPSPUBLICATION,nullptr,nullptr);
    if (publication_reader<0) {
      dds_delete(discovery_participant);
      discovery_participant=0;
      throw std::runtime_error("failed to create Cyclone publication discovery reader");
    }
    output=create_publisher<std_msgs::msg::String>("/phase5/command_audit",rclcpp::QoS(100));
    for (const auto &[kind,topic] : std::array<std::pair<std::string,std::string>,3>{{
        {"raw","/robot_1/cmd_vel_nav"}, {"smoothed","/robot_1/cmd_vel_smoothed"},
        {"checked","/robot_1/phase5/collision_checked"}}}) {
      inputs.push_back(create_subscription<Twist>(topic,rclcpp::QoS(100),
        [this,kind](const Twist::ConstSharedPtr message,const rclcpp::MessageInfo & info) {
          const auto & metadata=info.get_rmw_message_info();
          const auto gid=resolve_publisher(metadata.publisher_gid);
          const auto & t=message->twist;
          const auto wall=std::chrono::duration_cast<std::chrono::nanoseconds>(
              std::chrono::system_clock::now().time_since_epoch()).count();
          nlohmann::json data={{"kind",kind},{"stamp",int64_t(message->header.stamp.sec)*1000000000LL+message->header.stamp.nanosec},
            {"frame",message->header.frame_id},{"velocity",{t.linear.x,t.linear.y,t.angular.z}},
            {"unused_axes",{t.linear.z,t.angular.x,t.angular.y}},{"publisher_gid",gid},
            {"source_timestamp",metadata.source_timestamp},{"received_timestamp",metadata.received_timestamp},
            {"observer_wall",wall}};
          std_msgs::msg::String result; result.data=data.dump(); output->publish(result);
        }));
    }
  }

  ~CommandObserver() override {
    if (discovery_participant>0) dds_delete(discovery_participant);
  }
};

int main(int argc,char **argv) {
  rclcpp::init(argc,argv);
  rclcpp::spin(std::make_shared<CommandObserver>());
  rclcpp::shutdown();
}
