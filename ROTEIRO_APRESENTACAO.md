# Apresentação: eleição com três servidores

1. Inicie na pasta do projeto: `docker compose up --build`.
2. Aguarde os três servidores aparecerem como ativos e confira as mensagens `ELEICAO_RESULTADO` mais recentes. Uma eleição durante a inicialização pode ser transitória.
3. Abra outro terminal e execute `docker compose ps`.
4. Identifique o coordenador a partir do resultado mais recente.
5. Execute `docker compose stop serverN`, trocando `serverN` pelo coordenador real.
6. No primeiro terminal, acompanhe `ELEICAO_FALHA`, `ELEICAO_INICIADA`, `ELEICAO_VITORIA` e `ELEICAO_RESULTADO`. O novo coordenador deve ser um dos dois restantes.
7. Retorne o servidor: `docker compose start serverN`.

Se o projeto já estiver em execução, `docker compose up --build` pode recriar containers conforme as imagens forem reconstruídas. Nunca use `docker compose down -v` sem querer perder os bancos de dados.

OBS: Os eventos mostram o comportamento do algoritmo. Os três servidores podem inicialmente anunciar coordenadores diferentes durante o arranque; avalie o resultado depois da convergência.
