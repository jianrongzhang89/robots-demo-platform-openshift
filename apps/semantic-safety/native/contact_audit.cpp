// Read-only physics evidence. No velocity publisher, arm service or drive writes.
#include <chrono>
#include <atomic>
#include <map>
#include <mutex>
#include <set>
#include <string>
#include <thread>
#include <nlohmann/json.hpp>
#include <gz/plugin/Register.hh>
#include <gz/sim/System.hh>
#include <gz/sim/Util.hh>
#include <gz/sim/components/Collision.hh>
#include <gz/sim/components/ContactSensorData.hh>
#include <gz/sim/components/Link.hh>
#include <gz/sim/components/Name.hh>
#include <gz/sim/components/ParentEntity.hh>
#include <gz/transport/Node.hh>
#include <gz/msgs/stringmsg.pb.h>

namespace phase5 {
class ContactAudit : public gz::sim::System, public gz::sim::ISystemConfigure,
                     public gz::sim::ISystemPostUpdate {
  gz::transport::Node node;
  gz::transport::Node::Publisher publisher;
  std::map<gz::sim::Entity,std::string> collisions;
  std::map<std::pair<gz::sim::Entity,gz::sim::Entity>,uint64_t> counts;
  gz::sim::Entity body=gz::sim::kNullEntity;
  uint64_t steps=0, missing=0;
  int64_t lastPublish=0;
  nlohmann::json names=nlohmann::json::object();
  std::mutex mutex;
  std::string snapshot;
  std::atomic<bool> running{false};
  std::thread worker;
 public:
  ~ContactAudit() override {
    running=false;
    if(worker.joinable()) worker.join();
  }
  void Configure(const gz::sim::Entity & model, const std::shared_ptr<const sdf::Element> & config,
                 gz::sim::EntityComponentManager & ecm, gz::sim::EventManager &) override {
    const auto links=ecm.ChildrenByComponents(model,gz::sim::components::Link());
    for (auto link:links) {
      if(ecm.Component<gz::sim::components::Name>(link)->Data()=="base_link") body=link;
      for (auto collision:ecm.ChildrenByComponents(link,gz::sim::components::Collision())) {
        collisions[collision]=gz::sim::scopedName(collision,ecm,"::",false);
        if(!ecm.Component<gz::sim::components::ContactSensorData>(collision))
          ecm.CreateComponent(collision,gz::sim::components::ContactSensorData());
      }
    }
    const auto expected=config->Get<unsigned int>("expected_collision_count",4).first;
    if((expected!=4 && expected!=6) || collisions.size()!=expected || body==gz::sim::kNullEntity)
      throw std::runtime_error("unexpected qualified collision inventory or missing base_link");
    publisher=node.Advertise<gz::msgs::StringMsg>("/phase5/contact_audit");
    running=true;
    worker=std::thread([this] {
      std::string previous;
      while(running) {
        std::string data;
        {std::lock_guard<std::mutex> lock(mutex); data=snapshot;}
        if(!data.empty() && data!=previous) {
          gz::msgs::StringMsg message; message.set_data(data);
          publisher.Publish(message); previous=data;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
      }
    });
  }
  void PostUpdate(const gz::sim::UpdateInfo & info, const gz::sim::EntityComponentManager & ecm) override {
    if(info.paused) return;
    ++steps;
    auto details=nlohmann::json::array();
    std::set<std::pair<gz::sim::Entity,gz::sim::Entity>> stepPairs;
    for(const auto & entry:collisions) {
      const auto data=ecm.Component<gz::sim::components::ContactSensorData>(entry.first);
      if(!data) {++missing; continue;}
      for(const auto & contact:data->Data().contact()) {
        const auto a=contact.collision1().id(), b=contact.collision2().id();
        if(!a || !b || (!collisions.count(a) && !collisions.count(b))) {++missing; continue;}
        stepPairs.emplace(std::min(a,b),std::max(a,b));
        for(auto id:{a,b}) names[std::to_string(id)]=gz::sim::scopedName(id,ecm,"::",false);
        // Latest-step geometry is diagnostic; cumulative counters above remain
        // the coverage evidence, including contacts between published samples.
        auto positions=nlohmann::json::array(), normals=nlohmann::json::array();
        auto depths=nlohmann::json::array();
        for(const auto & p:contact.position()) positions.push_back({p.x(),p.y(),p.z()});
        for(const auto & n:contact.normal()) normals.push_back({n.x(),n.y(),n.z()});
        for(auto d:contact.depth()) depths.push_back(d);
        details.push_back({{"a",a},{"b",b},{"positions",positions},{"normals",normals},{"depths",depths}});
      }
    }
    for(const auto & pair:stepPairs) ++counts[pair];
    const auto wall=std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    if(wall-lastPublish<50000000) return;
    lastPublish=wall;
    auto pairs=nlohmann::json::array(), monitored=nlohmann::json::array();
    auto collisionPoses=nlohmann::json::object();
    for(const auto & pair:counts) pairs.push_back({{"a",pair.first.first},{"b",pair.first.second},
                                                  {"contact_steps",pair.second}});
    for(const auto & entry:collisions) {
      monitored.push_back({{"id",entry.first},{"name",entry.second}});
      const auto p=gz::sim::worldPose(entry.first,ecm);
      collisionPoses[std::to_string(entry.first)]={{"xyz",{p.X(),p.Y(),p.Z()}},
        {"rpy",{p.Rot().Roll(),p.Rot().Pitch(),p.Rot().Yaw()}}};
    }
    const auto pose=gz::sim::worldPose(body,ecm);
    const auto data=nlohmann::json({{"schema","phase5-contact-audit/v1"},{"steps",steps},
      {"sim_ns",std::chrono::duration_cast<std::chrono::nanoseconds>(info.simTime).count()},
      {"wall_ns",wall},{"missing",missing},{"monitored",monitored},{"names",names},{"pairs",pairs},
      {"base_pose",{{"xyz",{pose.X(),pose.Y(),pose.Z()}},
                    {"rpy",{pose.Rot().Roll(),pose.Rot().Pitch(),pose.Rot().Yaw()}}}},
      {"current_contacts",details},{"collision_poses",collisionPoses}}).dump();
    // Transport discovery/backpressure must never block the physics thread.
    {std::lock_guard<std::mutex> lock(mutex); snapshot=data;}
  }
};
}
GZ_ADD_PLUGIN(phase5::ContactAudit,gz::sim::System,phase5::ContactAudit::ISystemConfigure,
              phase5::ContactAudit::ISystemPostUpdate)
GZ_ADD_PLUGIN_ALIAS(phase5::ContactAudit,"phase5::ContactAudit")
