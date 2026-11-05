// Isolated real Nav2 LayeredCostmaps. No planner, controller or velocity publisher.
// G3 adds a configurable fixed frame and follows the observed base pose; no motion control.
#include <chrono>
#include <cmath>
#include <iostream>
#include <nav2_costmap_2d/layered_costmap.hpp>
#include <nav2_util/lifecycle_node.hpp>
#include <pluginlib/class_loader.hpp>
#include <std_srvs/srv/trigger.hpp>
#include <tf2_ros/transform_listener.hpp>
#include "demo_semantic_costmap/semantic_layer.hpp"

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<nav2_util::LifecycleNode>("phase4_costmap_observer", "");
  const auto global_frame = node->declare_parameter<std::string>("global_frame", "odom");
  auto group = node->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);
  auto tf = std::make_shared<tf2_ros::Buffer>(node->get_clock());
  tf2_ros::TransformListener listener(*tf, node, false);
  pluginlib::ClassLoader<nav2_costmap_2d::Layer> loader("nav2_costmap_2d", "nav2_costmap_2d::Layer");
  std::vector<std::unique_ptr<nav2_costmap_2d::LayeredCostmap>> maps;
  std::vector<std::shared_ptr<demo_semantic_costmap::SemanticLayer>> layers;
  std::vector<std::string> names{"global_semantic", "local_semantic"};
  for (int i = 0; i < 2; ++i) {
    maps.push_back(std::make_unique<nav2_costmap_2d::LayeredCostmap>(global_frame, i==1, false));
    maps.back()->resizeMap(i==0 ? 240 : 80, i==0 ? 240 : 80, 0.05, i==0 ? -6 : -2, i==0 ? -6 : -2);
    auto layer = std::dynamic_pointer_cast<demo_semantic_costmap::SemanticLayer>(
      loader.createSharedInstance("demo_semantic_costmap::SemanticLayer"));
    maps.back()->addPlugin(layer); layer->initialize(maps.back().get(), names[i], tf.get(), node, group);
    layers.push_back(layer);
  }
  using Trigger = std_srvs::srv::Trigger;
  auto clear = node->create_service<Trigger>("/phase4/clear", [&](const std::shared_ptr<Trigger::Request>, std::shared_ptr<Trigger::Response> response) {
    for (auto & layer : layers) {layer->reset();}
    response->success = true; response->message = "both observation epochs cleared";
  });
  auto deactivate = node->create_service<Trigger>("/phase4/deactivate", [&](const std::shared_ptr<Trigger::Request>, std::shared_ptr<Trigger::Response> response) {
    for (auto & layer : layers) {layer->deactivate();}
    response->success = true;
  });
  auto activate = node->create_service<Trigger>("/phase4/activate", [&](const std::shared_ptr<Trigger::Request>, std::shared_ptr<Trigger::Response> response) {
    for (auto & layer : layers) {layer->activate();}
    response->success = true;
  });
  uint64_t updates = 0;
  auto last = std::chrono::steady_clock::now();
  auto timer = node->create_wall_timer(std::chrono::milliseconds(33), [&] {
    auto now = std::chrono::steady_clock::now();
    double period = std::chrono::duration<double, std::milli>(now-last).count(); last=now;
    nlohmann::json row{{"update", ++updates}, {"period_ms", period},
      {"sim_ns", node->now().nanoseconds()}, {"maps", nlohmann::json::object()}};
    for (size_t i=0; i<maps.size(); ++i) {
      auto start = std::chrono::steady_clock::now();
      double x=0, y=0, yaw=0;
      try {
        const auto pose=tf->lookupTransform(global_frame, "base_footprint", tf2::TimePointZero);
        x=pose.transform.translation.x; y=pose.transform.translation.y;
        const auto &q=pose.transform.rotation;
        yaw=std::atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z));
      } catch (const tf2::TransformException &) {}
      maps[i]->updateMap(x,y,yaw);
      auto diag = layers[i]->diagnostics();
      diag["update_ms"] = std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-start).count();
      auto map = maps[i]->getCostmap(); size_t marked=0;
      for (unsigned int p=0; p<map->getSizeInCellsX()*map->getSizeInCellsY(); ++p)
      {if (map->getCharMap()[p]==200) {++marked;}}
      diag["marked_cells"] = marked; row["maps"][names[i]] = diag;
    }
    std::cout << row.dump() << std::endl;
  }, group);
  rclcpp::spin(node->get_node_base_interface());
  rclcpp::shutdown();
  return 0;
}
