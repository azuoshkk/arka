# Evolução do Dashgroup Arcanjo no T800

Este workspace contém o baseline da migração. O checkout original ainda precisa ser obtido com autenticação GitHub. Nenhum dashboard novo foi criado.

Comece por [docs/SESSION_STATE.md](docs/SESSION_STATE.md). A auditoria já realizada está em [docs/AUDIT.md](docs/AUDIT.md); não a repita integralmente.

O backend encontrado no robô está em `/home/ubuntu/scripts-ipq/beniFiles`. **Não execute a bridge original:** seu startup encerra processos das portas 5000 e 5055, atualmente usadas por voz e pescoço.

- [Arquitetura](docs/ARCHITECTURE.md)
- [Desenvolvimento](docs/DEVELOPMENT.md)
- [Implantação](docs/DEPLOYMENT.md)
- [Vídeo e medição real](docs/VIDEO.md)
- [Segurança](docs/SECURITY.md)
- [Solução de problemas](docs/TROUBLESHOOTING.md)

`prompt.md` contém informação sensível e está ignorado. Nunca usar `git add -f prompt.md`.
