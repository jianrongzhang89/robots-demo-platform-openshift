// Offline only: runs the actual native guard header against retained packets.
#include "lease_guard.hpp"
#include <fstream>
#include <iostream>
#include <cassert>
using namespace phase5;
using json=nlohmann::json;
Time at(int64_t wall) { return {wall,wall}; }
LeaseGuard seeded(const json &packet) {
  LeaseGuard guard;
  auto issued=packet.at("issued_wall").get<int64_t>();
  assert(guard.arm(packet.at("session"),true,at(issued-ms)));
  assert(guard.receive(packet.dump(),at(issued)));
  return guard;
}
int main(int argc,char **argv) {
  assert(argc==2); std::ifstream f(argv[1]); json input;f>>input;
  auto p5=input["run5"]["short_packet"];
  auto g5=seeded(input["run5"]["previous_packet"]);
  bool accepted5=g5.receive(p5.dump(),at(p5["issued_wall"]));
  assert(!accepted5 && g5.reason=="packet_invalid");
  auto p6=input["run6"]["renewal"];
  auto early=seeded(input["run6"]["previous_packet"]);
  auto late=early;
  auto boundary=early.expires;
  // Counterfactual reception times, NOT measured per-packet receive stamps.
  bool acceptedEarly=early.receive(p6.dump(),at(input["run6"]["worker_send_wall"]));
  bool acceptedLate=late.receive(p6.dump(),at(boundary+1));
  assert(acceptedEarly && !acceptedLate && late.reason=="lease_expired");
  json out={{"run5_zero_delivery_delay",{{"accepted",accepted5},{"reason",g5.reason}}},
    {"run6_counterfactual_receive_at_send",{{"accepted",acceptedEarly},{"reason",early.reason}}},
    {"run6_counterfactual_receive_1ns_after_old_expiry",{{"accepted",acceptedLate},{"reason",late.reason}}}};
  std::cout<<out.dump(2)<<"\n";
}
