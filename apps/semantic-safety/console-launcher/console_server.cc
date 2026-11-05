// Private fixture only: the native watchdog and evidence observers are unchanged.
// Console logging must not implicitly enable synchronous world-state recording.
#include <cstdlib>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#include <gz/common/Console.hh>
#include <gz/msgs/boolean.pb.h>
#include <gz/msgs/server_control.pb.h>
#include <gz/sim/Server.hh>
#include <gz/sim/ServerConfig.hh>
#include <gz/transport/Node.hh>

int main(int argc, char **argv)
{
  const char *domain = std::getenv("ROS_DOMAIN_ID");
  const char *partition = std::getenv("GZ_PARTITION");
  const char *ip = std::getenv("GZ_IP");
  if (argc != 3 || !domain || std::string(domain) != "85" ||
      !ip || std::string(ip) != "127.0.0.1" || !partition ||
      std::string(partition).find("phase5-watchdog-") != 0)
  {
    std::cerr << "private fixture world and new console directory required\n";
    return 2;
  }
  // Reject bad inputs using standard I/O before initializing Gazebo's logger:
  // its error reporting can recurse when the log directory cannot be created.
  namespace fs = std::filesystem;
  std::error_code error;
  if (!fs::is_regular_file(argv[1], error) || error)
    return 2;
  const fs::path logPath(argv[2]);
  if (!fs::create_directory(logPath, error) || error)
    return 2;
  {
    std::ofstream log(logPath / "server_console.log");
    if (!log) return 2;
  }
  gz::common::Console::SetVerbosity(2);
  gzLogInit(logPath.string(), "server_console.log");
  gz::sim::ServerConfig config;
  config.SetSdfFile(argv[1]);
  config.SetUseLogRecord(false);
  config.SetLogRecordPath(logPath.string());
  // Opt-in EGL headless rendering for GPU nodes: the default profile keeps
  // GLX on the Xvfb display with forced software rendering. Headless mode is
  // a rendering-context selection only; physics and the watchdog are
  // unchanged, and a failed render still fails the trial fail-closed.
  if (std::getenv("PHASE5_HEADLESS_RENDERING") &&
      std::string(std::getenv("PHASE5_HEADLESS_RENDERING")) == "1")
    config.SetHeadlessRendering(true);
  std::cout << "phase5 console-only server: world_recording=false\n" << std::flush;
  int result = 3;
  {
    gz::sim::Server server(config);
    std::cout << "phase5 lifecycle: constructed\n" << std::flush;
    if (server.EntityCount(0).has_value() && !server.EntityCount(1).has_value())
    {
      // Gazebo's built-in /server_control starts an internal Stop thread.
      // Run can return before that thread finishes joining the renderer, so
      // destruction can enter SensorsPrivate::Stop concurrently. Own the
      // stop worker here and join it BEFORE the Server destructor can run.
      std::mutex mutex;
      std::condition_variable changed;
      bool requested = false;
      std::atomic<bool> runFinished{false};
      gz::transport::Node stopNode;
      std::function<bool(const gz::msgs::ServerControl &, gz::msgs::Boolean &)> requestStop =
        [&](const gz::msgs::ServerControl &request, gz::msgs::Boolean &reply)
        {
          std::lock_guard<std::mutex> lock(mutex);
          const bool accepted = request.stop() && !runFinished.load();
          if (accepted) requested = true;
          reply.set_data(accepted);
          changed.notify_one();
          return true;
        };
      if (!stopNode.Advertise("/phase5/console_stop", requestStop))
      {
        std::cerr << "private serialized stop service unavailable\n";
        return 3;
      }
      std::thread stopWorker([&]
        {
          std::unique_lock<std::mutex> lock(mutex);
          changed.wait(lock, [&] {return requested || runFinished.load();});
          if (!requested) return;
          lock.unlock();
          // A request can arrive between advertising and entering Run.
          while (!server.Running() && !runFinished.load())
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
          if (!runFinished.load())
          {
            std::cout << "phase5 lifecycle: stop_begin\n" << std::flush;
            server.Stop();
            std::cout << "phase5 lifecycle: stop_end\n" << std::flush;
          }
        });
      try
      {
        result = server.Run(true, 0, false) ? 0 : 1;
      }
      catch (...)
      {
        result = 1;
        std::cerr << "private server Run threw an exception\n";
      }
      std::cout << "phase5 lifecycle: run_returned result=" << result << "\n" << std::flush;
      {
        std::lock_guard<std::mutex> lock(mutex);
        runFinished = true;
        changed.notify_one();
      }
      stopWorker.join();
      std::cout << "phase5 lifecycle: stop_worker_joined\n" << std::flush;
      stopNode.UnadvertiseSrv("/phase5/console_stop");
    }
    std::cout << "phase5 lifecycle: destructor_begin\n" << std::flush;
  }
  std::cout << "phase5 lifecycle: destructor_end\n" << std::flush;
  return result;
}
