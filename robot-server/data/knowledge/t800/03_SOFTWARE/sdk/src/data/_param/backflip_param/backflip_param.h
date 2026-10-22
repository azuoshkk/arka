#pragma once

#include "basic_param/basic_param.h"

namespace data {

class BackflipParam : public BasicParam {
 public:
  BackflipParam(std::string_view tag = "backflip") : BasicParam(tag) {}

  // CORREÇÃO CRÍTICA: O scope_ DEVE ser declarado ANTES das variáveis!
  DEFINE_PARAM_SCOPE(scope_);
  
  std::string LOAD_PARAM(policy_file);
  std::optional<std::vector<Eigen::VectorXd>> LOAD_PARAM(damping);

  // Um único Update() que lê tudo ao mesmo tempo
  void Update() override { 
      LOAD_PARAM(policy_file);
      LOAD_PARAM(damping); 
  }
};

}  // namespace data
