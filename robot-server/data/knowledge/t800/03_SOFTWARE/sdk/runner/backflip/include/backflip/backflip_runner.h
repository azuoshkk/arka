#pragma once

#include "basic/motion_runner.h"
#include "basic/runner_registry.h"
#include "backflip_param/backflip_param.h"
namespace runner {

class BackflipRunner : public MotionRunner {
 public:
  BackflipRunner(std::string_view name, const std::shared_ptr<data::DataStore>& data_store)
      : MotionRunner(name, data_store) {
    param_ = data::ParamManager::create<data::BackflipParam>();
  }
  ~BackflipRunner() = default;

  bool Enter() override;
  void Run() override;
  TransitionState TryExit() override;
  bool Exit() override;
  void End() override;
  void SetupContext() override;
  void TeardownContext() override;

  void Log();

 private:
  std::shared_ptr<data::BackflipParam> param_;
  Eigen::VectorXd damping_;
  Eigen::VectorXd zeros_;
};
}  // namespace runner

REGISTER_RUNNER(BackflipRunner, "backflip_runner", kMotion)
