#include <gtest/gtest.h>
#include <cstring>
#include <limits>
#include <nav2_costmap_2d/layered_costmap.hpp>
#include <nav2_util/lifecycle_node.hpp>
#include <pluginlib/class_loader.hpp>
#include <tf2_ros/buffer.hpp>
#include "demo_semantic_costmap/semantic_layer.hpp"

using demo_semantic_costmap::SemanticLayer;
using Json = nlohmann::json;
using nav2_costmap_2d::NO_INFORMATION;
namespace {
class TestLayer : public SemanticLayer {
public:
  int64_t wall{100000000000}, sim{10000000000};
  void replaceTfBuffer(tf2_ros::Buffer * buffer) {tf_ = buffer;}
protected:
  int64_t wallNow() const override {return wall;}
  int64_t simNow() const override {return sim;}
};
class Geometry : public nav2_costmap_2d::Layer {
public:
  void onInitialize() override {enabled_ = current_ = true;}
  void reset() override {}
  bool isClearable() override {return false;}
  void updateBounds(double, double, double, double *, double *, double *, double *) override {}
  void updateCosts(nav2_costmap_2d::Costmap2D & map, int minx, int miny, int maxx, int maxy) override {
    for (int y = miny; y < maxy; ++y) {
      for (int x = minx; x < maxx; ++x) {map.setCost(x, y, x == 2 && y == 2 ? 254 : x == 3 && y == 3 ? 255 : 0);}
    }
  }
};
struct Bundle {
  std::shared_ptr<sensor_msgs::msg::Image> mask;
  std::shared_ptr<sensor_msgs::msg::PointCloud2> cloud;
  Json timing;
};
class LayerTest : public ::testing::Test {
protected:
  std::shared_ptr<nav2_util::LifecycleNode> node;
  std::unique_ptr<tf2_ros::Buffer> tf;
  std::unique_ptr<nav2_costmap_2d::LayeredCostmap> map;
  std::shared_ptr<TestLayer> layer;
  rclcpp::CallbackGroup::SharedPtr group;
  int sequence{0};
  static void SetUpTestSuite() {if (!rclcpp::ok()) {rclcpp::init(0, nullptr);}}
  void SetUp() override {setup(false);}
  void setup(bool rolling) {
    layer.reset(); map.reset(); tf.reset(); node.reset();
    node = std::make_shared<nav2_util::LifecycleNode>("phase4_test", "");
    group = node->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive);
    tf = std::make_unique<tf2_ros::Buffer>(node->get_clock());
    geometry_msgs::msg::TransformStamped transform;
    transform.header.frame_id = "map"; transform.child_frame_id = "camera_color_optical_frame";
    transform.transform.translation.z = -1; transform.transform.rotation.w = 1;
    ASSERT_TRUE(tf->setTransform(transform, "phase4_test", true));
    map = std::make_unique<nav2_costmap_2d::LayeredCostmap>("map", rolling, false);
    map->resizeMap(6, 6, 1.0, 0, 0);
    auto geometry = std::make_shared<Geometry>();
    map->addPlugin(geometry); geometry->initialize(map.get(), "geometry", tf.get(), node, group);
    layer = std::make_shared<TestLayer>();
    map->addPlugin(layer); layer->initialize(map.get(), "semantic", tf.get(), node, group);
    labels(); advance(0.01); update();
  }
  void labels() {layer->receiveLabels(Json({{"policy", "avoid-target/v1"}, {"generation", 1},
      {"labels", {{"0", "unobserved"}, {"1", "traversable"}, {"2", "avoid_target"}}},
      {"active_labels", {0, 2}}}).dump());}
  void advance(double seconds) {layer->sim += int64_t(seconds*1e9); layer->wall += int64_t(seconds*1e9);}
  void freshTf() {tf = std::make_unique<tf2_ros::Buffer>(node->get_clock()); layer->replaceTfBuffer(tf.get());}
  void update(double x = 3, double y = 3) {map->updateMap(x, y, 0);}
  Bundle bundle(std::vector<uint8_t> ids = {2}, std::vector<float> xyz = {0.25, 0.25, 1.0}) {
    Bundle b;
    b.mask = std::make_shared<sensor_msgs::msg::Image>();
    auto & m = *b.mask;
    m.header.frame_id = "camera_color_optical_frame";
    m.header.stamp = rclcpp::Time(layer->sim);
    m.width = ids.size(); m.height = 1; m.encoding = "mono8"; m.step = m.width; m.data = ids;
    b.cloud = std::make_shared<sensor_msgs::msg::PointCloud2>(); auto & c = *b.cloud;
    c.header = m.header; c.width = m.width; c.height = 1; c.point_step = 12; c.row_step = c.width*12;
    for (int i = 0; i < 3; ++i) {sensor_msgs::msg::PointField f;
      f.name = std::vector<std::string>{"x", "y", "z"}[i]; f.offset = i*4; f.datatype = 7; f.count = 1; c.fields.push_back(f);}
    c.data.resize(xyz.size()*4); std::memcpy(c.data.data(), xyz.data(), c.data.size());
    b.timing = {{"capture", {{"stamp_ns", layer->sim}, {"frame_id", m.header.frame_id}}},
      {"capture_wall_ns", layer->wall}, {"identity", {{"robot", "robot_1"}, {"stream", "camera/color"},
      {"generation", 1}, {"epoch", "producer-1"}, {"request_id", std::to_string(++sequence)}}},
      {"mask_sha256", SemanticLayer::digest(m.data)}, {"cloud_sha256", SemanticLayer::digest(c.data)}};
    return b;
  }
  void send(const Bundle & b) {layer->receiveMask(b.mask); layer->receiveCloud(b.cloud); layer->receiveTiming(b.timing.dump());}
  unsigned char cost(int x, int y) {return map->getCostmap()->getCost(x, y);}
  void expectClear() {
    update(); EXPECT_EQ(cost(0, 0), 0); EXPECT_EQ(cost(2, 2), 254); EXPECT_EQ(cost(3, 3), 255);
    EXPECT_EQ(layer->diagnostics()["cells"], 0); EXPECT_EQ(layer->getCost(0, 0), NO_INFORMATION);
  }
};
TEST_F(LayerTest, ExactGridProjectionAndMaximumMerge) {
  send(bundle({2,2,2,0}, {0.25,0.25,1, 2.25,2.25,1, 3.25,3.25,1, 1.25,1.25,1})); update();
  for (int y = 0; y < 6; ++y) {for (int x = 0; x < 6; ++x) {
    EXPECT_EQ(cost(x,y), x==2 && y==2 ? 254 : x==3 && y==3 ? 255 : x==0 && y==0 ? 200 : 0);
  }}
  EXPECT_EQ(layer->diagnostics()["cells"], 3); EXPECT_EQ(layer->diagnostics()["accepted"], 1);
}
TEST_F(LayerTest, CaptureTimeTransformNotLatest) {
  // Replace the static transform with a dynamic-only buffer. Capture-time
  // translation is x=1; at a newer timestamp it is x=2.
  freshTf();
  geometry_msgs::msg::TransformStamped tr; tr.header.frame_id="map";
  tr.child_frame_id="camera_color_optical_frame"; tr.transform.rotation.w=1;
  tr.transform.translation.z=-1; tr.transform.translation.x=1;
  tr.header.stamp=rclcpp::Time(layer->sim); ASSERT_TRUE(tf->setTransform(tr,"test",false));
  auto b=bundle(); advance(0.1); tr.transform.translation.x=2;
  tr.header.stamp=rclcpp::Time(layer->sim); ASSERT_TRUE(tf->setTransform(tr,"test",false));
  send(b); update(); EXPECT_EQ(cost(1,0),200); EXPECT_EQ(cost(2,0),0);
}
TEST_F(LayerTest, MissingTransformRejectsWithoutBufferingObservations) {
  freshTf(); send(bundle()); expectClear(); EXPECT_EQ(layer->diagnostics()["rejected"],1);
}
TEST_F(LayerTest, InvalidDepthAndHeightAreNotProjected) {
  send(bundle({2,2,2,2}, {NAN,0,1, 0,0,-1, 0,0,2, 9,9,1})); expectClear();
  EXPECT_EQ(layer->diagnostics()["accepted"],1);
}
TEST_F(LayerTest, TargetRemovalDoesNotDeclareFloorAndExpiresFromCapture) {
  send(bundle()); advance(0.5); send(bundle({0})); update(); EXPECT_EQ(cost(0,0),200);
  advance(0.5); expectClear(); EXPECT_EQ(layer->diagnostics()["accepted"],2);
}
TEST_F(LayerTest, ExpiryUsesWallTimeEvenWhenSimulationPaused) {
  send(bundle()); update(); layer->wall += 1000000000; expectClear();
}
TEST_F(LayerTest, ExpiryUsesSimulationTimeAlso) {
  send(bundle()); update(); layer->sim += 1000000000; expectClear();
}
TEST_F(LayerTest, ResetClearsRasterTemporalAndPartialPairState) {
  send(bundle()); update(); advance(0.1); auto late=bundle(); layer->receiveMask(late.mask);
  layer->reset(); EXPECT_EQ(layer->diagnostics()["pending"],0); expectClear();
  layer->receiveCloud(late.cloud); layer->receiveTiming(late.timing.dump()); send(late); expectClear();
  advance(0.01); send(bundle()); update(); EXPECT_EQ(cost(0,0),200);
}
TEST_F(LayerTest, DeactivateReactivateRequiresNewCapture) {
  auto old=bundle(); send(old); update(); layer->deactivate(); expectClear(); send(old); expectClear();
  layer->activate(); send(old); expectClear(); advance(0.01); send(bundle()); update(); EXPECT_EQ(cost(0,0),200);
}
TEST_F(LayerTest, RollingWindowEvictsOldWorldCellsAndDoesNotResurrect) {
  setup(true); send(bundle()); update(); EXPECT_EQ(cost(0,0),200);
  update(15,15); EXPECT_EQ(layer->diagnostics()["cells"],0); update(); expectClear();
}
TEST_F(LayerTest, DuplicateAndOutOfOrderCapturesCannotRefreshLifetime) {
  auto old=bundle(); send(old); advance(0.1); send(bundle()); send(old); update();
  EXPECT_EQ(layer->diagnostics()["accepted"],2); EXPECT_EQ(layer->diagnostics()["rejected"],1);
  advance(1); expectClear();
}
TEST_F(LayerTest, SimulationClockResetRejectsDelayedOldEpochThenAcceptsFresh) {
  auto old=bundle(); send(old); update(); layer->sim=1000000000; layer->wall+=100000000;
  update(); send(old); expectClear(); advance(0.01); auto fresh=bundle();
  fresh.timing["identity"]["epoch"]="producer-2"; send(fresh); update(); EXPECT_EQ(cost(0,0),200);
}
TEST_F(LayerTest, RepeatedSimulationStampCannotMixDifferentEpochPayloads) {
  auto old=bundle(); send(old); update(); layer->reset(); advance(0.1);
  layer->sim=old.timing["capture"]["stamp_ns"].get<int64_t>();
  auto fresh=bundle({0}); fresh.timing["identity"]["epoch"]="producer-2";
  layer->receiveTiming(fresh.timing.dump()); layer->receiveMask(old.mask); layer->receiveCloud(fresh.cloud);
  expectClear(); EXPECT_EQ(layer->diagnostics()["reason"],"payload_digest_mismatch");
}
TEST_F(LayerTest, InvalidLayoutsUnknownLabelsAndHashesFailClosed) {
  auto b=bundle(); b.mask->step=2; send(b); expectClear();
  advance(0.01); b=bundle({7}); send(b); expectClear();
  advance(0.01); b=bundle(); b.timing.erase("mask_sha256"); send(b); expectClear();
  advance(0.01); b=bundle(); b.cloud->fields[2].offset=4; send(b); expectClear();
  EXPECT_EQ(layer->diagnostics()["accepted"],0); EXPECT_EQ(layer->diagnostics()["rejected"],4);
}
TEST_F(LayerTest, WrongLabelsInvalidateExistingObservations) {
  send(bundle()); update(); layer->receiveLabels("{}"); expectClear();
  advance(0.01); send(bundle()); expectClear(); labels(); advance(0.01); send(bundle()); update(); EXPECT_EQ(cost(0,0),200);
}
TEST_F(LayerTest, WrongGenerationRobotAndExpiredCaptureRejected) {
  auto b=bundle(); b.timing["identity"]["generation"]=2; send(b);
  advance(0.01); b=bundle(); b.timing["identity"]["robot"]="robot_2"; send(b);
  advance(0.01); b=bundle(); advance(0.6); send(b); expectClear();
  EXPECT_EQ(layer->diagnostics()["rejected"],3);
}
TEST_F(LayerTest, PendingBufferBoundAndArbitraryMessageArrivalOrder) {
  for(int i=0;i<30;++i) {advance(0.001); layer->receiveMask(bundle().mask);}
  EXPECT_LE(layer->diagnostics()["pending"].get<int>(),8);
  advance(0.01); auto b=bundle(); layer->receiveTiming(b.timing.dump()); layer->receiveCloud(b.cloud); layer->receiveMask(b.mask);
  update(); EXPECT_EQ(cost(0,0),200); EXPECT_EQ(layer->diagnostics()["accepted"],1);
}
TEST_F(LayerTest, ResizeIsAnEpochClearNotRasterOnly) {
  send(bundle()); update(); map->resizeMap(8,8,1,0,0); expectClear();
}
TEST_F(LayerTest, NonzeroFractionalMapOriginUsesExactGridCells) {
  map->resizeMap(6,6,1,-0.3,-0.3); advance(0.01);
  send(bundle({2}, {0.8,0.8,1})); update(); EXPECT_EQ(cost(1,1),200); EXPECT_EQ(cost(0,0),0);
}
TEST_F(LayerTest, OpticalFrameRotationProjectsForwardDepthOntoGround) {
  freshTf(); geometry_msgs::msg::TransformStamped tr;
  tr.header.frame_id="map"; tr.child_frame_id="camera_color_optical_frame";
  tr.transform.translation.z=1;
  tr.transform.rotation.x=-0.5; tr.transform.rotation.y=0.5;
  tr.transform.rotation.z=-0.5; tr.transform.rotation.w=0.5;
  ASSERT_TRUE(tf->setTransform(tr,"test",true));
  send(bundle({2}, {-0.25,0.95,1.25})); update(); EXPECT_EQ(cost(1,0),200); EXPECT_EQ(cost(0,0),0);
}
TEST_F(LayerTest, ArrivalBetweenBoundsAndCostsIsNotFalselyReportedAsApplied) {
  send(bundle()); update(); advance(0.01);
  double minx=1e9,miny=1e9,maxx=-1e9,maxy=-1e9;
  layer->updateBounds(3,3,0,&minx,&miny,&maxx,&maxy);
  send(bundle({2},{1.25,0.25,1}));
  layer->updateCosts(*map->getCostmap(),0,0,6,6);
  EXPECT_FALSE(layer->diagnostics()["last"].contains("costmap_wall_ns"));
  update(); EXPECT_TRUE(layer->diagnostics()["last"].contains("costmap_wall_ns")); EXPECT_EQ(cost(1,0),200);
}
TEST_F(LayerTest, ResetBetweenBoundsAndCostsCannotRepaintOldRaster) {
  send(bundle()); update(); layer->reset();
  map->getCostmap()->setCost(0,0,0); layer->updateCosts(*map->getCostmap(),0,0,6,6);
  EXPECT_EQ(cost(0,0),0); EXPECT_EQ(layer->diagnostics()["cells"],0);
}
TEST_F(LayerTest, PluginlibLoadsInstalledLayer) {
  pluginlib::ClassLoader<nav2_costmap_2d::Layer> loader("nav2_costmap_2d","nav2_costmap_2d::Layer");
  auto loaded=loader.createSharedInstance("demo_semantic_costmap::SemanticLayer"); EXPECT_NE(loaded,nullptr);
}
}  // namespace
