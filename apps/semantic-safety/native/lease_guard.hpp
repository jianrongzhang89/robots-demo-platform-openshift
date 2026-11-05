#pragma once
#include <cmath>
#include <cstdint>
#include <set>
#include <string>
#include <nlohmann/json.hpp>

namespace phase5 {
constexpr int64_t ms = 1000000;
struct Time { int64_t steady, wall; };
// Process-local core; callers serialize access. Wall times alone cross transport.
class LeaseGuard {
 public:
  bool armed = false;
  bool pending = false;
  double vx = 0, wz = 0;
  std::string session, reason = "startup_disarmed";
  int64_t deadline = 0, expires = 0, sequence = -1, trigger = 0;
  std::set<std::string> used;
  Time previous{0, 0};

  void stop(const std::string & why, Time now) {
    if (armed || pending) { reason = why; trigger = now.steady; }
    armed = pending = false; vx = wz = 0; session.clear();
  }
  void tick(Time now) {
    if (previous.steady && (now.steady < previous.steady ||
        std::abs((now.wall-previous.wall)-(now.steady-previous.steady)) > 20*ms))
      stop("clock_discontinuity", now);
    previous = now;
    if ((armed || pending) && (now.steady >= deadline || now.wall >= expires)) {
      const auto boundary = std::min(now.steady, deadline);
      stop(pending ? "arm_handshake_expired" : "lease_expired", now); trigger = boundary;
    }
  }
  bool arm(const std::string & token, bool stationary, Time now) {
    tick(now);
    if (armed || pending || !stationary || token.size() != 36 || used.count(token) || used.size() >= 1024)
      return false;
    // UUID-shaped token; no command may adopt a token by itself.
    for (size_t i=0; i<token.size(); ++i) {
      if (i==8 || i==13 || i==18 || i==23) { if (token[i]!='-') return false; }
      else if (!((token[i]>='0' && token[i]<='9') || (token[i]>='a' && token[i]<='f'))) return false;
    }
    // Arming reserves a new session but grants ZERO wheel authority until a
    // fresh, bounded command arrives. Control-plane handshake latency is not
    // a reason to extend any moving-command lease beyond 80 ms.
    used.insert(token); session=token; pending=true; reason="awaiting_first_packet";
    sequence=-1; trigger=0; deadline=now.steady+2000*ms; expires=now.wall+2000*ms;
    return true;
  }
  bool receive(const std::string & wire, Time now) {
    tick(now);  // Late callbacks must not hide expiration.
    if (!armed && !pending) return false;
    try {
      if (wire.size()>2048) throw std::runtime_error("oversize");
      auto p=nlohmann::json::parse(wire);
      for (auto key : {"sequence", "issued_wall", "expires_wall"})
        if (!p.at(key).is_number_integer() || p.at(key).get<int64_t>()<0)
          throw std::runtime_error("integer");
      const auto seq=p.at("sequence").get<int64_t>();
      const auto issued=p.at("issued_wall").get<int64_t>();
      const auto end=p.at("expires_wall").get<int64_t>();
      const auto & v=p.at("velocity");
      if (!v.is_array() || v.size()!=3) throw std::runtime_error("velocity");
      for (auto & x:v) if (!x.is_number()) throw std::runtime_error("number");
      double x=v[0], y=v[1], z=v[2];
      if (p.at("schema")!="phase5-drive/v1" || p.at("session")!=session || seq<=sequence ||
          end<=issued || end-issued>80*ms || issued>now.wall+2*ms ||
          !std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z) ||
          x<-.10 || x>.15 || y!=0 || std::abs(z)>.5) throw std::runtime_error("invalid");
      // Drain pre-arm traffic delayed by service discovery without granting
      // motion or moving the handshake barrier. Once moving, expired traffic
      // remains a latched fault. A cancelled/expired session is never revived.
      if(end<=now.wall+2*ms) {
        if(pending) return false;
        throw std::runtime_error("expired");
      }
      armed=true; pending=false;
      sequence=seq; expires=end-2*ms; deadline=now.steady+(expires-now.wall);
      vx=x; wz=z; reason="armed"; return true;
    } catch (...) { stop("packet_invalid", now); return false; }
  }
};
}  // namespace phase5
