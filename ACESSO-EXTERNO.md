# Arka: acesso externo e ensino

## Iniciar

```bash
cd ~/"Área de trabalho"/arcanjinho
./scripts/start-web.sh
```

O marcador local `.local/remote-enabled` ativa o túnel junto ao servidor. HTTPS/LAN continuam em `:8444`, e a página auxiliar do certificado continua em `:8082`. Nenhuma porta do roteador precisa ser aberta. O túnel usa apenas `https://127.0.0.1:8444`, valida o certificado pela CA local e exige o login já configurado. Qdrant, Ollama, ROS2 e áudio não recebem túneis próprios.

Consulte `logs/remote-access.log` e `cat .local/demo-url`. Abra a URL HTTPS mostrada no notebook/celular de outra rede e entre com seu login. A URL só existe depois que o túnel conectar. Se o servidor já estiver rodando sem o túnel, execute `./scripts/start-demo.sh` em outro terminal.

O processo tenta reconectar automaticamente. Mantenha o notebook ligado, com internet e sem suspensão. Fechar o programa fecha seu túnel. Quick Tunnel não tem garantia de disponibilidade nem endereço fixo: o endereço pode mudar após reiniciar. Para uso permanente com URL estável, será necessário configurar um túnel nomeado com conta/domínio ou uma VPN privada; essa etapa não foi configurada.

Para iniciar apenas na LAN: `ARKA_REMOTE_ACCESS=0 ./scripts/start-web.sh`. Não existe token Cloudflare no projeto: o túnel temporário não usa conta. Credenciais da aplicação e certificados permanecem em `.local/`, ignorada pelo Git; não publique essa pasta. Nenhuma nova instalação foi necessária.

Se aparecer falha de DNS/timeout para `api.trycloudflare.com`, o túnel ainda não conectou. Verifique a conectividade/DNS da rede; não substitua isso por abertura de portas no roteador.

## Ensinar informações compartilhadas

Entre como administrador e diga, por exemplo:

> Arka, aprenda que a reunião da equipe acontece às sextas, às dez horas, na sala Azul.

A confirmação só aparece depois de salvar e indexar no RAG. Outra sessão pode perguntar “Onde e quando acontece a reunião da equipe?”. Também é possível publicar/editar/desativar em **Ensinar → texto/FAQ**. Perguntas semelhantes são recuperadas por significado. A informação publicada é compartilhada entre usuários, mas o histórico da conversa continua individual.

Use um comando explícito como “aprenda que” ou “guarde que”. Uma conversa casual não publica automaticamente tudo que as pessoas dizem. Respostas produzidas pela própria Arka não são gravadas como fatos novos. Administradores devem revisar o conteúdo publicado; espectadores podem consultar, mas não ensinar. Isso atualiza a base de conhecimento, não os pesos do modelo. A coleção original não foi reindexada.

## Olhos

Após 60 segundos sem interação, os olhos fecham. Movimento, toque ou teclado acordam a Arka. Clique nos olhos para receber uma piscadinha. Fala, escuta e processamento mantêm seus estados originais.
