// Additional evidence harness linked to the already-built candidate library.
// Reuse its exact synthetic fixtures; never substitute this input for SAM3.
#include "../test/test_semantic_layer.cpp"
#include <iostream>

namespace {
TEST_F(LayerTest, StoreActualGridAndBufferSnapshots) {
  auto snapshot = [&](const char * stage) {
    Json raster = Json::array(), semantic = Json::array();
    for (unsigned int y=0; y<6; ++y) {
      Json row=Json::array(), layer_row=Json::array();
      for (unsigned int x=0; x<6; ++x) {row.push_back(cost(x,y)); layer_row.push_back(layer->getCost(x,y));}
      raster.push_back(row); semantic.push_back(layer_row);
    }
    std::cout << "GRID_EVIDENCE " << Json({{"stage",stage},{"master",raster},{"semantic",semantic},
        {"buffers",layer->diagnostics()}}).dump() << std::endl;
  };
  snapshot("before");
  auto old=bundle({2,2,2}, {0.25,0.25,1, 2.25,2.25,1, 3.25,3.25,1});
  send(old); update(); snapshot("marked");
  EXPECT_EQ(cost(0,0),200); EXPECT_EQ(cost(2,2),254); EXPECT_EQ(cost(3,3),255);
  layer->reset(); expectClear(); snapshot("reset");
  send(old); expectClear(); snapshot("delayed_pre_reset_result");
  advance(0.01); send(bundle()); update(); EXPECT_EQ(cost(0,0),200); snapshot("fresh_capture");
  advance(1); expectClear(); snapshot("expired");
}
}  // namespace
