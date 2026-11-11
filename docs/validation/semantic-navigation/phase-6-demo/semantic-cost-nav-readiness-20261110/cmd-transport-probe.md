# Phase 6 command transport probe

Date: 2026-11-10/11

The AMCL-seeded semantic-on run produced a valid Nav2 command (`/cmd_vel` peaked at 0.06 m/s), but the simulator body and wheel odometry stayed stationary for the full 180 s. The robot remained at `(15.4014, -31.594)` with zero velocity. The Nav2 global semantic layer stayed at 917 lethal cells, and the map-frame plan kept 0.6764 m minimum hull clearance.

Bridge discovery looked configured: the Nav2 bridge logged `Route Publisher (ROS:/cmd_vel -> Zenoh:robot_1/cmd_vel) created`; the simulator bridge logged `Route Subscriber (Zenoh:robot_1/cmd_vel -> ROS:/robot_1/cmd_vel) created`; Gazebo listed a publisher and subscriber on `/robot_1/cmd_vel`. However, a safe zero-Twist probe published repeatedly on Nav2 `/cmd_vel` was not observed by either a simulator ROS subscriber on `/robot_1/cmd_vel` or a Gazebo Transport echo on `/robot_1/cmd_vel`. The route exists in discovery, but Twist samples are not arriving at the simulator. This is the remaining actuation-path failure; the exact point of loss is not yet isolated.

Evidence is summarized in [`semantic-cost-nav-amcl-fix-live-summary.json`](semantic-cost-nav-amcl-fix-live-summary.json), with the full run in [`semantic-cost-nav-amcl-fix-live-20261110.json`](semantic-cost-nav-amcl-fix-live-20261110.json) and Nav2 logs in [`semantic-cost-nav-amcl-fix-live-nav2.log`](semantic-cost-nav-amcl-fix-live-nav2.log).
