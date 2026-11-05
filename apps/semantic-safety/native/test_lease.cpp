#include "lease_guard.hpp"
#include <gtest/gtest.h>
using namespace phase5;
const std::string token="00000000-0000-4000-a000-000000000001";
Time at(int64_t n) { return {1000*ms+n*ms,100000*ms+n*ms}; }
nlohmann::json packet(int n=1) {
  return {{"schema","phase5-drive/v1"},{"session",token},{"sequence",n},
    {"issued_wall",at(n).wall},{"expires_wall",at(n+80).wall},{"velocity",{.1,0.,0.}}};
}
TEST(Lease, Startup) {LeaseGuard g; EXPECT_FALSE(g.receive(packet().dump(),at(1))); EXPECT_DOUBLE_EQ(g.vx,0);}
TEST(Lease, StationaryRequired) {LeaseGuard g; EXPECT_FALSE(g.arm(token,false,at(0))); EXPECT_FALSE(g.arm("x",true,at(0)));}
TEST(Lease, Expiration) {
  LeaseGuard g; ASSERT_TRUE(g.arm(token,true,at(0))); ASSERT_TRUE(g.receive(packet().dump(),at(1)));
  g.tick(at(78)); EXPECT_DOUBLE_EQ(g.vx,.1); g.tick(at(79)); EXPECT_DOUBLE_EQ(g.vx,0);
  EXPECT_EQ(g.reason,"lease_expired"); EXPECT_FALSE(g.receive(packet(80).dump(),at(80)));
}
TEST(Lease, LateCallback) {LeaseGuard g; g.arm(token,true,at(0)); g.receive(packet().dump(),at(1)); EXPECT_FALSE(g.receive(packet(79).dump(),at(79)));}
TEST(Lease, NoSessionReuse) {LeaseGuard g; g.arm(token,true,at(0)); g.stop("cancel",at(1)); EXPECT_FALSE(g.arm(token,true,at(2)));}
TEST(Lease, NewSessionExplicit) {LeaseGuard g; g.arm(token,true,at(0)); g.stop("cancel",at(1)); EXPECT_TRUE(g.arm("00000000-0000-4000-a000-000000000002",true,at(2))); EXPECT_FALSE(g.receive(packet(3).dump(),at(3)));}
TEST(Lease, InvalidPacketsLatch) {
  for(int i=0;i<10;++i) {
    LeaseGuard g; g.arm(token,true,at(0)); auto p=packet();
    switch(i) {
      case 0:p["velocity"]={.16,0,0};break; case 1:p["velocity"]={0,.01,0};break;
      case 2:p["velocity"]={0,0,.51};break; case 3:p["expires_wall"]=at(200).wall;break;
      case 4:p["issued_wall"]=at(10).wall;break; case 5:p["expires_wall"]=at(0).wall;break;
      case 6:p["sequence"]=true;break; case 7:p["session"]="old";break;
      case 8:p["velocity"]={true,0,0};break; case 9:p["schema"]="unknown";break;
    }
    EXPECT_FALSE(g.receive(p.dump(),at(1)))<<i; EXPECT_FALSE(g.armed); EXPECT_DOUBLE_EQ(g.vx,0);
  }
}
TEST(Lease, Replay) {LeaseGuard g;g.arm(token,true,at(0));g.receive(packet().dump(),at(1));EXPECT_FALSE(g.receive(packet().dump(),at(2)));}
TEST(Lease, ClockJump) {LeaseGuard g;g.arm(token,true,at(0));g.receive(packet().dump(),at(1));g.tick({at(2).steady,at(100).wall});EXPECT_FALSE(g.armed);EXPECT_EQ(g.reason,"clock_discontinuity");}
TEST(Lease, Malformed) {LeaseGuard g;g.arm(token,true,at(0));EXPECT_FALSE(g.receive("not json",at(1)));EXPECT_FALSE(g.armed);}
TEST(Lease, UpstreamShorterDeadline) {LeaseGuard g;g.arm(token,true,at(0));auto p=packet();p["expires_wall"]=at(20).wall;g.receive(p.dump(),at(1));g.tick(at(18));EXPECT_FALSE(g.armed);}
TEST(Lease, StopRetainsFirstReason) {LeaseGuard g;g.arm(token,true,at(0));g.stop("cancel",at(1));g.stop("late",at(2));EXPECT_EQ(g.reason,"cancel");}
TEST(Lease, PendingHandshakeNeverGrantsMotion) {
  LeaseGuard g; g.arm(token,true,at(0));g.tick(at(500));
  EXPECT_FALSE(g.armed);EXPECT_TRUE(g.pending);EXPECT_DOUBLE_EQ(g.vx,0);
  EXPECT_TRUE(g.receive(packet(501).dump(),at(501)));EXPECT_TRUE(g.armed);
  g.tick(at(579));EXPECT_FALSE(g.armed);EXPECT_EQ(g.reason,"lease_expired");
}
TEST(Lease, HandshakeTimeoutAndCancelInvalidateSession) {
  LeaseGuard g;g.arm(token,true,at(0));g.tick(at(2000));
  EXPECT_FALSE(g.pending);EXPECT_FALSE(g.receive(packet(2001).dump(),at(2001)));
  EXPECT_EQ(g.reason,"arm_handshake_expired");
  LeaseGuard h;h.arm(token,true,at(0));h.stop("cancel",at(1));
  EXPECT_FALSE(h.receive(packet(2).dump(),at(2)));
}
TEST(Lease, ExpiredPreArmTrafficCannotBlockFreshFirstPacket) {
  LeaseGuard g;g.arm(token,true,at(0));EXPECT_FALSE(g.receive(packet().dump(),at(150)));
  EXPECT_TRUE(g.pending);EXPECT_FALSE(g.armed);EXPECT_DOUBLE_EQ(g.vx,0);
  EXPECT_TRUE(g.receive(packet(151).dump(),at(151)));
  EXPECT_TRUE(g.armed);g.tick(at(229));EXPECT_FALSE(g.armed);
}
