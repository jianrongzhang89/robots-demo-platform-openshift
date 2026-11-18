from launch import LaunchDescription
from launch_ros.actions import Node
import os


def generate_launch_description():
    params=os.path.join(os.environ['WAREHOUSE_RUN_DIR'],'nav2.yaml')
    nodes=[('nav2_map_server','map_server'),('nav2_planner','planner_server'),
           ('nav2_controller','controller_server'),('nav2_bt_navigator','bt_navigator')]
    actions=[Node(package=pkg,executable=name,name=name,output='screen',parameters=[params]) for pkg,name in nodes]
    actions.append(Node(package='nav2_lifecycle_manager',executable='lifecycle_manager',
        name='lifecycle_manager_navigation',output='screen',parameters=[{'use_sim_time':True,
        'autostart':True,'node_names':[name for _,name in nodes],'bond_timeout':10.}]))
    return LaunchDescription(actions)
