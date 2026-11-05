#include "lease_guard.hpp"
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <random>
#include <string>
#include <thread>
#include <gz/plugin/Register.hh>
#include <gz/sim/System.hh>
#include <gz/sim/Model.hh>
#include <gz/sim/Link.hh>
#include <gz/sim/Util.hh>
#include <gz/sim/components/JointVelocityCmd.hh>
#include <gz/transport/Node.hh>
#include <gz/msgs/boolean.pb.h>
#include <gz/msgs/stringmsg.pb.h>
#include <gz/msgs/twist.pb.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>
#include <cstring>

namespace phase5 {
Time now() {
  return {std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count(),
    std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count()};
}
class DriveWatchdog : public gz::sim::System, public gz::sim::ISystemConfigure,
                      public gz::sim::ISystemConfigurePriority,
                      public gz::sim::ISystemPreUpdate, public gz::sim::ISystemPostUpdate {
  std::mutex mutex;
  LeaseGuard guard;
  gz::transport::Node node;
  gz::transport::Node::Publisher drive, status;
  gz::sim::Link body;
  gz::sim::Entity left=gz::sim::kNullEntity, right=gz::sim::kNullEntity;
  std::atomic<bool> running{false};
  std::thread worker;
  // UDP companion path for the high-frequency drive traffic. The gz
  // transport node is shared with the sensor publications: rendering the
  // perception camera (12 MB/s) holds the node's shared mutex long enough
  // to delay this watchdog's status PUBLICATION by hundreds of milliseconds
  // (measured p95 ~575 ms under the SAM3 observation load), which the
  // coordinator's 20 ms capture-bracket joins cannot absorb. Status leaves
  // through a non-blocking UDP sendto that no transport mutex can block, and
  // leases arrive through a dedicated UDP listener thread feeding the same
  // guard. The qualified gz paths all remain active and unchanged; the rare
  // arm/stop services stay on gz.
  int statusFd=-1, leaseFd=-1;
  std::thread udpWorker;
  std::thread statusSender;
  // Dedicated UDP status sender thread (series-2 trial 000 lesson, October
  // 2026): even with the sendto ordered FIRST inside the publish worker's
  // iteration, a gz status.Publish blocked ~100 ms on the console server's
  // shared transport mutex under load delays the NEXT iteration's sendto —
  // the packet reached the fixture already 104 ms after its physical
  // capture and latched native_capture_stale mid-trial. The publish worker
  // now only swaps the latest message into a slot; this thread wakes and
  // sends immediately, fully decoupled from every gz publish. The sendto
  // itself is unchanged (best effort, non-blocking); the gz status topic
  // remains active for the suites that subscribe it through gz.
  std::mutex udpSendMutex;
  std::condition_variable udpSendCV;
  std::string udpSendSlot;
  bool udpSendStop=false;
  struct sockaddr_in statusAddr{};
  std::atomic<int64_t> udpSent{0}, udpReceived{0};
  int64_t lastPhysics=0, stoppedSince=0, lastStatus=0, lastUdpStatus=0, previousSim=-1;
  bool stopped=false;
  int64_t receivedPackets=0, lastPacketWall=0, appliedSteady=0;
  int64_t stopAppliedSteady=0, stopAppliedTrigger=0;
  double appliedVx=0, appliedWz=0;
  nlohmann::json physical=nullptr;
  const std::string clockEpoch=std::to_string(now().wall)+"-"+std::to_string(std::random_device{}());
  uint64_t physicsSequence=0;

  bool Arm(const gz::msgs::StringMsg & request, gz::msgs::Boolean & response) {
    std::lock_guard<std::mutex> lock(mutex);
    auto t=now();
    const bool stationary=stopped && stoppedSince && t.steady-stoppedSince>=250*ms &&
      lastPhysics && t.steady-lastPhysics<100*ms;
    response.set_data(guard.arm(request.data(), stationary, t));
    return true;
  }
  bool Stop(const gz::msgs::StringMsg & request, gz::msgs::Boolean & response) {
    std::lock_guard<std::mutex> lock(mutex);
    guard.stop(request.data().substr(0,128), now());
    response.set_data(true); return true;
  }
  void Receive(const gz::msgs::StringMsg & message) {
    std::lock_guard<std::mutex> lock(mutex);
    ++receivedPackets; lastPacketWall=now().wall;
    guard.receive(message.data(), now());
  }
  void UdpReceive() {
    char buffer[4096];
    while(running) {
      const ssize_t n=recv(leaseFd,buffer,sizeof(buffer)-1,0);
      if(n<=0) continue;  // closed at shutdown, or a malformed datagram
      buffer[n]=0;
      std::string datagram(buffer,n);
      std::lock_guard<std::mutex> lock(mutex);
      ++receivedPackets; ++udpReceived; lastPacketWall=now().wall;
      // Lease packets are the coordinator's JSON (leading '{'); arm/stop
      // carry a "arm:"/"stop:" prefix. Arm applies the same stationary
      // proof as the gz service; its ACCEPTANCE is proven to the
      // coordinator by the status stream's session, and a rejected arm
      // simply never appears there (the first-command timeout stops the
      // chain fail-closed). Stops are backstopped by lease expiry.
      if(datagram.rfind("arm:",0)==0) {
        auto t=now();
        const bool stationary=stopped && stoppedSince && t.steady-stoppedSince>=250*ms &&
          lastPhysics && t.steady-lastPhysics<100*ms;
        guard.arm(datagram.substr(4), stationary, t);
      } else if(datagram.rfind("stop:",0)==0) {
        guard.stop(datagram.substr(4,128), now());
      } else {
        guard.receive(datagram, now());
      }
    }
  }
  void Publish() {
    // Runs independently of ROS and simulation time. No cached nonzero value
    // is republished after expiry, even while the physics clock is paused.
    gz::msgs::Twist command;
    gz::msgs::StringMsg message;
    bool publishStatus=false;
    {
    std::lock_guard<std::mutex> lock(mutex);
    auto t=now();  // sample only after taking the lock; callbacks may have advanced time
    guard.tick(t);
    if (!lastPhysics || t.steady-lastPhysics>=100*ms) guard.stop("physics_heartbeat_lost",t);
    command.mutable_linear()->set_x(guard.vx);
    command.mutable_angular()->set_z(guard.wz);
    if (t.steady-lastStatus>=5*ms) {
      nlohmann::json data={{"schema","phase5-drive-status/v1"},{"wall_ns",t.wall},
        {"steady_ns",t.steady},{"armed",guard.armed},{"pending",guard.pending},{"reason",guard.reason},
        {"session",guard.session},{"sequence",guard.sequence},{"trigger_steady_ns",guard.trigger},
        {"vx",guard.vx},{"wz",guard.wz},{"physical",physical},{"clock_epoch",clockEpoch},
        {"received_packets",receivedPackets},{"last_packet_wall_ns",lastPacketWall},
        {"stop_applied_steady_ns",stopAppliedSteady},{"stop_applied_trigger_ns",stopAppliedTrigger},
        {"applied_steady_ns",appliedSteady},{"applied_vx",appliedVx},{"applied_wz",appliedWz}};
      message.set_data(data.dump()); publishStatus=true;
      lastStatus=t.steady;
    }
    }
    // Never hold the control-state mutex across transport calls. Service
    // discovery / network backpressure must not block physics-thread expiry.
    // The UDP companion status is filled from PostUpdate (the physics
    // thread) — this worker's gz publishes can no longer affect it at all.
    drive.Publish(command);
    if(publishStatus) status.Publish(message);
  }
  void UdpSendLoop() {
    while (running) {
      std::string datagram;
      {
        std::unique_lock<std::mutex> slot(udpSendMutex);
        udpSendCV.wait(slot, [this] { return udpSendStop || !udpSendSlot.empty(); });
        if (udpSendStop) return;
        datagram = std::move(udpSendSlot);
        udpSendSlot.clear();
      }
      if (statusFd>=0 && sendto(statusFd,datagram.data(),datagram.size(),
          MSG_DONTWAIT,reinterpret_cast<const sockaddr*>(&statusAddr),
          sizeof(statusAddr))>=0) ++udpSent;
    }
  }
 public:
  gz::sim::System::PriorityType ConfigurePriority() override { return 100; }
  ~DriveWatchdog() override {
    running=false;
    {
      std::lock_guard<std::mutex> slot(udpSendMutex);
      udpSendStop=true;
    }
    udpSendCV.notify_all();
    if(statusSender.joinable()) statusSender.join();
    // shutdown() reliably wakes a recv blocked in the listener thread;
    // close() alone may leave it sleeping on the detached description.
    if(leaseFd>=0) shutdown(leaseFd,SHUT_RDWR);
    if(udpWorker.joinable()) udpWorker.join();
    if(worker.joinable()) worker.join();
    if(leaseFd>=0) close(leaseFd);
    if(statusFd>=0) close(statusFd);
  }
  void Configure(const gz::sim::Entity & entity, const std::shared_ptr<const sdf::Element> & sdf,
                 gz::sim::EntityComponentManager & ecm, gz::sim::EventManager &) override {
    gz::sim::Model model(entity);
    body=gz::sim::Link(model.LinkByName(ecm,"base_link"));
    if(!body.Valid(ecm)) throw std::runtime_error("base_link missing");
    left=model.JointByName(ecm,"left_wheel_joint");
    right=model.JointByName(ecm,"right_wheel_joint");
    if(left==gz::sim::kNullEntity || right==gz::sim::kNullEntity)
      throw std::runtime_error("qualified wheel joints missing");
    body.EnableVelocityChecks(ecm);
    auto copy=sdf->Clone();
    const auto output=copy->Get<std::string>("output_topic");
    const auto prefix=copy->Get<std::string>("prefix");
    if(output!="/phase5/internal_drive" || prefix!="/phase5/drive")
      throw std::runtime_error("unexpected Phase 5 actuator topics");
    drive=node.Advertise<gz::msgs::Twist>(output);
    status=node.Advertise<gz::msgs::StringMsg>(prefix+"/status");
    if(!node.Subscribe(prefix+"/lease", &DriveWatchdog::Receive,this) ||
       !node.Advertise(prefix+"/arm", &DriveWatchdog::Arm,this) ||
       !node.Advertise(prefix+"/stop", &DriveWatchdog::Stop,this))
      throw std::runtime_error("watchdog endpoints unavailable");
    // UDP companion endpoints, loopback only: status to 45985, leases on 45986.
    statusFd=socket(AF_INET,SOCK_DGRAM,0);
    leaseFd=socket(AF_INET,SOCK_DGRAM,0);
    if(statusFd<0 || leaseFd<0) throw std::runtime_error("udp companion sockets unavailable");
    fcntl(statusFd,F_SETFL,O_NONBLOCK);
    int reuse=1;
    setsockopt(leaseFd,SOL_SOCKET,SO_REUSEADDR,&reuse,sizeof(reuse));
    statusAddr.sin_family=AF_INET;
    statusAddr.sin_port=htons(45985);
    inet_pton(AF_INET,"127.0.0.1",&statusAddr.sin_addr);
    struct sockaddr_in leaseAddr{};
    leaseAddr.sin_family=AF_INET;
    leaseAddr.sin_port=htons(45986);
    inet_pton(AF_INET,"127.0.0.1",&leaseAddr.sin_addr);
    if(bind(leaseFd,reinterpret_cast<const sockaddr*>(&leaseAddr),sizeof(leaseAddr))!=0)
      throw std::runtime_error("udp lease endpoint unavailable");
    // running must be set BEFORE any thread starts: every worker loop
    // checks it on entry (series-11 trial 000-off — the lease listener saw
    // running==false and exited instantly, received_packets stayed 0, and
    // the armed session expired at its first-command timeout; the sender
    // thread's creation between the listener's start and the flag widened
    // the pre-existing race enough to flip it).
    running=true;
    udpWorker=std::thread([this] { UdpReceive(); });
    statusSender=std::thread([this] { UdpSendLoop(); });
    worker=std::thread([this] {
      while(running) {
        Publish();
        std::this_thread::sleep_for(std::chrono::milliseconds(5));
      }
    });
  }
  void PreUpdate(const gz::sim::UpdateInfo & info, gz::sim::EntityComponentManager & ecm) override {
    std::lock_guard<std::mutex> lock(mutex);
    auto t=now();
    auto sim=std::chrono::duration_cast<std::chrono::nanoseconds>(info.simTime).count();
    if(info.paused) guard.stop("simulation_paused",t);
    if(previousSim>=0 && sim<previousSim) {guard.stop("simulation_reset",t); stoppedSince=0;}
    previousSim=sim;
    guard.tick(t);
    // Last actuator writer, after the retained DiffDrive's default priority 0.
    // This closes loss of the internal transport/worker too: authority is
    // evaluated on the physics thread, not dependent on delivery of a zero
    // Twist. DiffDrive remains only the existing wheel-odometry producer.
    const double lv=(guard.vx-guard.wz*.287/2)/.033;
    const double rv=(guard.vx+guard.wz*.287/2)/.033;
    for(auto pair : {std::make_pair(left,lv),std::make_pair(right,rv)}) {
      auto component=ecm.Component<gz::sim::components::JointVelocityCmd>(pair.first);
      if(component) component->Data()={pair.second};
      else ecm.CreateComponent(pair.first,gz::sim::components::JointVelocityCmd({pair.second}));
    }
    appliedSteady=t.steady; appliedVx=guard.vx; appliedWz=guard.wz;
    // Retain the FIRST physics write of zero for this stop, not the timestamp
    // of a later diagnostic sample (which otherwise overstates stop latency).
    if(guard.armed || guard.pending) {stopAppliedSteady=0; stopAppliedTrigger=0;}
    else if(guard.trigger && guard.trigger!=stopAppliedTrigger) {
      stopAppliedSteady=t.steady; stopAppliedTrigger=guard.trigger;
    }
  }
  void PostUpdate(const gz::sim::UpdateInfo & info, const gz::sim::EntityComponentManager & ecm) override {
    auto linear=body.WorldLinearVelocity(ecm), angular=body.WorldAngularVelocity(ecm);
    auto pose=gz::sim::worldPose(body.Entity(),ecm);
    std::lock_guard<std::mutex> lock(mutex);
    auto t=now(); lastPhysics=t.steady;
    const bool quiet=linear && angular && linear->Length()<.005 && angular->Length()<.02 && !info.paused;
    if(quiet && !stopped) stoppedSince=t.steady;
    if(!quiet) stoppedSince=0;
    stopped=quiet;
    physical={{"wall_ns",t.wall},{"steady_ns",t.steady},{"sequence",++physicsSequence},{"paused",info.paused},
      {"sim_ns",std::chrono::duration_cast<std::chrono::nanoseconds>(info.simTime).count()},
      {"x",pose.Pos().X()},{"y",pose.Pos().Y()},{"z",pose.Pos().Z()},
      {"yaw",pose.Rot().Yaw()},{"velocity_valid",bool(linear && angular)},
      {"speed",linear ? linear->Length() : -1},{"angular_speed",angular ? angular->Length() : -1}};
    // Fill the UDP companion status slot HERE, on the physics thread where
    // the capture is born (series-5 trial 000-on lesson): the publish
    // worker's previous-iteration gz publish can still block ~100 ms and
    // delay the next slot fill, aging the capture past the 100 ms bound
    // even with the slot swap first within the iteration. Filling from
    // PostUpdate makes the companion's latency the sender thread's wake
    // time (microseconds); the gz status/drive publishes remain on the
    // worker at their own cadence for the suites that use them.
    if (t.steady-lastUdpStatus>=5*ms) {
      nlohmann::json data={{"schema","phase5-drive-status/v1"},{"wall_ns",t.wall},
        {"steady_ns",t.steady},{"armed",guard.armed},{"pending",guard.pending},{"reason",guard.reason},
        {"session",guard.session},{"sequence",guard.sequence},{"trigger_steady_ns",guard.trigger},
        {"vx",guard.vx},{"wz",guard.wz},{"physical",physical},{"clock_epoch",clockEpoch},
        {"received_packets",receivedPackets},{"last_packet_wall_ns",lastPacketWall},
        {"stop_applied_steady_ns",stopAppliedSteady},{"stop_applied_trigger_ns",stopAppliedTrigger},
        {"applied_steady_ns",appliedSteady},{"applied_vx",appliedVx},{"applied_wz",appliedWz}};
      lastUdpStatus=t.steady;
      {
        std::lock_guard<std::mutex> slot(udpSendMutex);
        udpSendSlot = data.dump();
      }
      udpSendCV.notify_one();
    }
  }
};
}  // namespace phase5
GZ_ADD_PLUGIN(phase5::DriveWatchdog,gz::sim::System,phase5::DriveWatchdog::ISystemConfigure,
              phase5::DriveWatchdog::ISystemConfigurePriority,
              phase5::DriveWatchdog::ISystemPreUpdate,phase5::DriveWatchdog::ISystemPostUpdate)
GZ_ADD_PLUGIN_ALIAS(phase5::DriveWatchdog,"phase5::DriveWatchdog")
