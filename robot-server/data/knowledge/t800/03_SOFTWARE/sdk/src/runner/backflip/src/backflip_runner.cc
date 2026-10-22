#include "backflip/backflip_runner.h"

#include <glog/logging.h>
#include "tool/concatenate_vector.h"

namespace runner {

void BackflipRunner::SetupContext() { data_store_->parallel_by_classic_parser.store(true); }

void BackflipRunner::TeardownContext() {}

bool BackflipRunner::Enter() {
  if (!param_tag_.empty()) {
    param_ = data::ParamManager::create<data::BackflipParam>(param_tag_);
  }

  zeros_ = Eigen::VectorXd::Zero(model_param_->num_total_joints);

  GetMutableOutput().Reset();
  return true;
}

void BackflipRunner::Run() {
  Eigen::VectorXd q_real_, qd_real_, q_des_, qd_des_, joint_kp_, joint_kd_, tau_ff_des_;

  q_real_ = Eigen::VectorXd::Zero(model_param_->num_total_joints);
  qd_real_ = Eigen::VectorXd::Zero(model_param_->num_total_joints);
  q_des_ = Eigen::VectorXd::Zero(model_param_->num_total_joints);
  qd_des_ = Eigen::VectorXd::Zero(model_param_->num_total_joints);
  tau_ff_des_ = Eigen::VectorXd::Zero(model_param_->num_total_joints);
  joint_kp_ = Eigen::VectorXd::Zero(model_param_->num_total_joints);
  joint_kd_ = Eigen::VectorXd::Zero(model_param_->num_total_joints);

  data_store_->joint_info.GetState(data::JointInfoType::kPosition, q_real_);
  data_store_->joint_info.GetState(data::JointInfoType::kVelocity, qd_real_);

  GetMutableOutput().SetCommand(q_des_, qd_des_, joint_kp_, joint_kd_, tau_ff_des_);
}

TransitionState BackflipRunner::TryExit() { return TransitionState::kCompleted; }

bool BackflipRunner::Exit() { return true; }

void BackflipRunner::End() {}
}