// Observe actual simulator actuator commands and velocities, without commanding motion.
#include <gz/sim/System.hh>
#include <gz/sim/Model.hh>
#include <gz/sim/components/JointForceCmd.hh>
#include <gz/sim/components/JointVelocity.hh>
#include <gz/plugin/Register.hh>
#include <fstream>
#include <iomanip>
#include <cstdlib>
#include <cmath>
#include <string>

class WarehouseTelemetry : public gz::sim::System,
  public gz::sim::ISystemConfigure, public gz::sim::ISystemPreUpdate
{
  gz::sim::Entity left{}, right{};
  std::ofstream trace;
  std::ofstream energy;
  double previous=-1;
  double previousEnergy=-1;
  double cumulativeWh=0.0;
  double soc=0.8;
  double capacityWh=24.0;
  double efficiency=0.6;
  double auxiliaryW=2.0;
 public:
  void Configure(const gz::sim::Entity &_entity, const std::shared_ptr<const sdf::Element> &,
    gz::sim::EntityComponentManager &_ecm, gz::sim::EventManager &) override
  {
    gz::sim::Model model(_entity);
    left=model.JointByName(_ecm,"left_wheel_joint");
    right=model.JointByName(_ecm,"right_wheel_joint");
    const char *file=std::getenv("WAREHOUSE_TORQUE_TRACE");
    trace.open(file ? file : "/work/torque.csv");
    trace << "sim_s,left_rad_s,right_rad_s,left_nm,right_nm\n";
    trace << std::setprecision(12);
    const char *energyFile=std::getenv("WAREHOUSE_ENERGY_TRACE");
    energy.open(energyFile ? energyFile : "/work/energy.csv");
    auto envDouble=[](const char *name,double fallback) {
      const char *value=std::getenv(name);
      if (!value) return fallback;
      char *end=nullptr;
      double parsed=std::strtod(value,&end);
      return end && end!=value && *end=='\0' && std::isfinite(parsed) ? parsed : fallback;
    };
    soc=envDouble("WAREHOUSE_INITIAL_SOC",0.8);
    capacityWh=envDouble("WAREHOUSE_BATTERY_CAPACITY_WH",24.0);
    efficiency=envDouble("WAREHOUSE_DRIVE_EFFICIENCY",0.6);
    auxiliaryW=envDouble("WAREHOUSE_AUXILIARY_W",2.0);
    if (soc<0.0 || soc>1.0) soc=0.8;
    if (capacityWh<=0.0) capacityWh=24.0;
    if (efficiency<=0.0 || efficiency>1.0) efficiency=0.6;
    if (auxiliaryW<0.0) auxiliaryW=2.0;
    energy << "sim_s,dt_s,left_rad_s,right_rad_s,left_nm,right_nm,left_mech_w,right_mech_w,drive_electrical_w,auxiliary_w,battery_w,incremental_wh,cumulative_wh,soc_fraction\n";
    energy << std::setprecision(12);
  }
  void PreUpdate(const gz::sim::UpdateInfo &_info,
    gz::sim::EntityComponentManager &_ecm) override
  {
    double now=std::chrono::duration<double>(_info.simTime).count();
    if (_info.paused || now-previous<0.02) return;
    auto lv=_ecm.Component<gz::sim::components::JointVelocity>(left);
    auto rv=_ecm.Component<gz::sim::components::JointVelocity>(right);
    auto lf=_ecm.Component<gz::sim::components::JointForceCmd>(left);
    auto rf=_ecm.Component<gz::sim::components::JointForceCmd>(right);
    if (!lv || !rv || !lf || !rf || lv->Data().empty() || rv->Data().empty()
      || lf->Data().empty() || rf->Data().empty()) return;
    previous=now;
    trace << now << ',' << lv->Data()[0] << ',' << rv->Data()[0]
      << ',' << lf->Data()[0] << ',' << rf->Data()[0] << '\n';
    trace.flush();
    double dt=previousEnergy<0.0 ? 0.0 : now-previousEnergy;
    previousEnergy=now;
    if (dt<0.0 || dt>0.2) return;
    const double leftMech=std::max(0.0,lf->Data()[0]*lv->Data()[0]);
    const double rightMech=std::max(0.0,rf->Data()[0]*rv->Data()[0]);
    const double driveW=(leftMech+rightMech)/efficiency;
    const double batteryW=driveW+auxiliaryW;
    const double incrementWh=batteryW*dt/3600.0;
    cumulativeWh+=incrementWh;
    soc=std::max(0.0,soc-incrementWh/capacityWh);
    energy << now << ',' << dt << ',' << lv->Data()[0] << ',' << rv->Data()[0]
      << ',' << lf->Data()[0] << ',' << rf->Data()[0] << ',' << leftMech << ','
      << rightMech << ',' << driveW << ',' << auxiliaryW << ',' << batteryW << ','
      << incrementWh << ',' << cumulativeWh << ',' << soc << '\n';
    energy.flush();
  }
};
GZ_ADD_PLUGIN(WarehouseTelemetry, gz::sim::System,
  WarehouseTelemetry::ISystemConfigure, WarehouseTelemetry::ISystemPreUpdate)
