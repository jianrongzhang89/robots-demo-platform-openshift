// Private performance diagnostic only. Equivalent server defaults to gz sim
// -r -s -v 2, with explicit console logging and an isolated recorder on/off test.
#include <cstdlib>
#include <iostream>
#include <string>
#include <gz/common/Console.hh>
#include <gz/sim/Server.hh>
#include <gz/sim/ServerConfig.hh>

int main(int argc, char **argv)
{
  const char *domain = std::getenv("ROS_DOMAIN_ID");
  const char *partition = std::getenv("GZ_PARTITION");
  if (argc != 4 || (std::string(argv[3]) != "on" && std::string(argv[3]) != "off") ||
      !domain || std::string(domain) != "85" ||
      !partition || std::string(partition).find("phase5-watchdog-") != 0)
  {
    std::cerr << "private diagnostic world, console path, and on/off required\n";
    return 2;
  }
  gz::common::Console::SetVerbosity(2);
  gzLogInit(argv[2], "server_console.log");
  gz::sim::ServerConfig config;
  config.SetSdfFile(argv[1]);
  const bool recording = std::string(argv[3]) == "on";
  config.SetUseLogRecord(recording);
  config.SetLogRecordPath(argv[2]);
  std::cout << "phase5 diagnostic: world recording " << argv[3] << '\n' << std::flush;
  gz::sim::Server server(config);
  return server.Run(true, 0, false) ? 0 : 1;
}
