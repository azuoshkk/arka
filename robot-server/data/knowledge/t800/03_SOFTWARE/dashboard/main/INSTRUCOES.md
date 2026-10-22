# INSTRUÇÕES GERAIS DE DESENVOLVIMENTO E MANUTENÇÃO DO PROJETO

## 1. Documentação e atualização do README

O README.md deve ser mantido sempre atualizado durante todo o desenvolvimento do projeto.

A cada nova implementação, alteração ou correção, revise a documentação para garantir que ela reflita fielmente o estado atual do sistema.

O README deve conter, sempre que aplicável:

* Descrição do projeto e seu objetivo.
* Funcionalidades implementadas.
* Funcionalidades em desenvolvimento.
* Como o sistema funciona e sua arquitetura.
* Tecnologias, bibliotecas e frameworks utilizados.
* Instruções de instalação, configuração e execução.
* Estrutura de diretórios e componentes relevantes.
* Integrações, dependências e requisitos.
* Alterações importantes realizadas em cada versão.
* Limitações conhecidas e próximos passos.

**Regra fundamental:** Nunca considere uma funcionalidade concluída sem verificar se a documentação correspondente está atualizada.

Não invente funcionalidades, tecnologias ou comportamentos que não estejam efetivamente implementados.

---

## 2. Versionamento e identificação de versões

Todo o projeto deve seguir uma estratégia clara e consistente de versionamento.

O objetivo é garantir rastreabilidade, facilitar a identificação de alterações e permitir que qualquer pessoa compreenda qual versão do sistema está sendo executada.

### 2.1. Versionamento do sistema

* Adotar Semantic Versioning (SemVer), seguindo o padrão `MAJOR.MINOR.PATCH` (ex.: `v1.0.0`).
* Incrementar a versão de acordo com a natureza da alteração:

  * **MAJOR:** Alterações incompatíveis ou mudanças significativas.
  * **MINOR:** Novas funcionalidades compatíveis com a versão anterior.
  * **PATCH:** Correções de bugs e ajustes compatíveis.
* Evitar alterar a versão sem uma justificativa clara e documentada.
* Garantir que a versão apresentada corresponda ao código efetivamente executado.

### 2.2. Exibição da versão no aplicativo

Sempre que tecnicamente possível, disponibilizar a versão atual do sistema na interface do aplicativo.

A versão deve ser apresentada de forma clara, por exemplo:

* Rodapé da aplicação.
* Tela de configurações ou informações do sistema.
* Tela de diagnóstico ou informações técnicas.

Quando aplicável, incluir também:

* Nome do projeto.
* Número da versão.
* Data ou identificador do build.
* Commit ou revisão de referência.

A implementação deve ser consistente com a arquitetura existente e não deve comprometer a experiência do usuário.

### 2.3. Versionamento em vídeos e gravações

Quando o sistema realizar gravações de vídeo, demonstrações ou registros de funcionamento, incluir a versão do software de forma visível sempre que possível.

A identificação pode ser apresentada por meio de:

* Overlay no vídeo.
* Informações na tela de gravação.
* Metadados, quando suportados.
* Nome do arquivo, quando fizer sentido.

Exemplo:

`Projeto v1.2.0 | Build 2026-09-18`

A versão exibida deve corresponder à versão utilizada durante a gravação. Não adicionar informações que não possam ser confirmadas.

### 2.4. Commits e histórico de alterações

Manter um histórico de commits organizado, descritivo e rastreável.

Boas práticas:

* Utilizar mensagens de commit claras e objetivas.
* Descrever o que foi alterado e, quando necessário, o motivo.
* Evitar mensagens genéricas como `update`, `fix` ou `changes`.
* Agrupar alterações relacionadas em commits coerentes.
* Criar tags de versão para releases relevantes, quando aplicável.
* Não declarar uma versão como finalizada sem garantir que as alterações estejam registradas corretamente.

Exemplos:

```text
feat: adiciona integração com sensor LiDAR
fix: corrige falha no processamento das imagens
docs: atualiza README com instruções de execução
refactor: reorganiza módulo de navegação
release: v1.2.0
```

### 2.5. Registro de versões no README

Sempre que possível, manter no README ou em um CHANGELOG.md um histórico das versões e suas principais alterações.

Exemplo:

```markdown
## Histórico de versões

### v1.2.0
- Adicionada nova funcionalidade de navegação.
- Melhorado o processamento de dados dos sensores.
- Corrigidos problemas de estabilidade.

### v1.1.0
- Implementadas melhorias na interface.
- Adicionados novos recursos de monitoramento.
```

---

## 3. Qualidade do código e prevenção de bugs

Todo código desenvolvido ou modificado deve passar por uma revisão técnica antes de ser considerado concluído.

O objetivo é garantir um sistema confiável, sustentável, seguro e com o menor número possível de falhas.

### 3.1. Revisão obrigatória

Antes de finalizar qualquer implementação:

* Revisar o código alterado.
* Verificar se a solução atende ao requisito solicitado.
* Identificar possíveis bugs, falhas lógicas e comportamentos inesperados.
* Avaliar tratamento de erros e exceções.
* Verificar compatibilidade com o restante do sistema.
* Garantir que a alteração não quebre funcionalidades existentes.
* Avaliar desempenho, uso de memória e recursos quando relevante.
* Eliminar código desnecessário, duplicado ou inconsistente.
* Confirmar que as dependências e configurações estão corretas.

**Não considerar uma implementação concluída apenas porque o código executa sem apresentar erros imediatos.**

---

## 4. Testes e validação

Sempre que possível, realizar testes antes e depois das alterações.

Os testes devem ser adequados ao tipo de implementação, incluindo:

* Testes funcionais.
* Testes de integração.
* Testes de regressão.
* Validação de entradas e saídas.
* Testes de desempenho, quando necessário.
* Testes de cenários de falha e recuperação.

Quando um teste não puder ser executado, registrar essa limitação e informar o que ainda precisa ser validado.

Nunca afirmar que uma funcionalidade foi testada, validada ou corrigida sem que isso tenha sido efetivamente verificado.

---

## 5. Segurança e confiabilidade

Priorizar a estabilidade e a segurança do sistema em todas as implementações.

* Não expor credenciais, tokens ou informações sensíveis.
* Validar entradas de usuários e dados externos.
* Utilizar tratamento adequado de falhas.
* Evitar alterações que comprometam funcionalidades críticas.
* Considerar estados de emergência e comportamentos seguros quando o sistema controlar hardware ou equipamentos.
* Preservar a integridade dos dados e das configurações existentes.

Em sistemas robóticos, priorizar comportamentos seguros, incluindo parada controlada, tratamento de perda de sensores e recuperação de falhas, conforme os requisitos do projeto.

---

## 6. Processo obrigatório antes de concluir uma tarefa

Sempre seguir este fluxo:

1. **Compreender:** Analisar o requisito e o código existente antes de implementar.
2. **Planejar:** Identificar os arquivos afetados, dependências e possíveis impactos.
3. **Implementar:** Desenvolver a solução seguindo boas práticas de engenharia de software.
4. **Revisar:** Inspecionar o código em busca de bugs, inconsistências e melhorias.
5. **Testar:** Executar os testes e validações aplicáveis.
6. **Documentar:** Atualizar o README e demais documentos necessários.
7. **Versionar:** Registrar as alterações na estratégia de versionamento do projeto.
8. **Validar:** Confirmar que a implementação atende ao requisito original e não compromete funcionalidades existentes.

### Critério de conclusão

Uma tarefa só deve ser considerada concluída quando:

* A funcionalidade estiver implementada de acordo com o requisito.
* O código tiver sido revisado.
* Os testes aplicáveis tiverem sido executados ou suas limitações registradas.
* A documentação estiver atualizada.
* O versionamento estiver consistente.
* Os problemas conhecidos estiverem identificados e comunicados.

**Princípio central: desenvolver com qualidade, documentar com precisão, versionar com clareza e validar antes de entregar.**
