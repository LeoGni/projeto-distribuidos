# Sistema de mensagens distribuídas

Projeto de Sistemas Distribuídos dividido em cinco partes: Request-Reply, Publisher-Subscriber, relógios e heartbeat, eleição e consistência com replicação.

O sistema é executado sem interação manual. Dois bots em JavaScript conversam com três servidores em Python. A comunicação é feita com ZeroMQ e as mensagens são serializadas com MessagePack. Cada servidor possui seu próprio banco SQLite.

## Serviços

| Serviço | Função |
|---|---|
| `broker` | Intermedia os pedidos dos bots (ROUTER na porta 5555 e DEALER na 5556) |
| `pubproxy` | Distribui publicações por tópico (XSUB 5557 e XPUB 5558) |
| `referencia` | Controla a lista de servidores ativos, ranks e heartbeat (5559) |
| `server1`, `server2` e `server3` | Processam os pedidos, publicam mensagens, participam da eleição e sincronizam os bancos (5560 entre servidores) |
| `bot1` e `bot2` | Fazem login, criam canais, se inscrevem e publicam mensagens |

A linguagem Python é usada nos servidores e serviços auxiliares; JavaScript é usado nos bots. Essa combinação contempla as duas linguagens exigidas para uma entrega individual.

## Execução

Requisitos: Docker Engine com o plugin Docker Compose, ou Docker Desktop em funcionamento.

Na pasta onde está o `docker-compose.yaml`:

```sh
docker compose up --build
```

Em outro terminal:

```sh
docker compose ps
docker compose logs -f server1 server2 server3 bot1 bot2
```

Os bots iniciam sozinhos e enviam grupos de dez mensagens, com um segundo entre elas. Para encerrar sem apagar os bancos, use `Ctrl+C` e, se desejar, `docker compose down`. Não use `docker compose down -v` se quiser preservar o histórico.

## Parte 1: Request-Reply

O bot faz login, consulta os canais e cria canais usando pedidos REQ/REP. Nomes de canais aceitam letras, números, `_` e `-`, com até 32 caracteres. Os logins e canais são gravados com horário de envio e recebimento.

## Parte 2: Publisher-Subscriber

O bot escolhe canais para inscrição e envia as publicações primeiro ao servidor. O servidor valida a requisição, grava a mensagem e publica no tópico correspondente. O proxy distribui as mensagens para os assinantes. A tela mostra os envios e recebimentos com identificação do canal e horários.

## Parte 3: Relógios e heartbeat

Os processos mantêm um contador lógico. O valor é incrementado antes do envio e atualizado com o maior valor recebido. O serviço de referência distribui ranks e mantém a lista de servidores ativos. Os servidores enviam heartbeat a cada dez pedidos de clientes e também periodicamente quando estão ociosos.

## Parte 4: Eleição

Os servidores usam seus ranks para eleger um coordenador. Um servidor pode solicitar eleição por REQ/REP diretamente aos outros, e o eleito anuncia seu nome no tópico `servers`. Se o coordenador falha, os outros iniciam nova eleição. O coordenador realiza a sincronização física usando amostras dos relógios dos servidores conforme o algoritmo de Berkeley. O serviço de referência não devolve o horário no heartbeat.

## Parte 5: Consistência e replicação

O broker entrega cada pedido a apenas um servidor. Sem replicação, os servidores manteriam histórias diferentes. Para resolver isso, foi adotada **replicação assíncrona por antientropia**, com troca periódica de registros entre servidores.

Cada servidor grava as operações em seu SQLite e mantém uma tabela de registros com identificador único, servidor de origem e número sequencial da origem. Entram nessa tabela os logins, canais, pedidos, respostas e publicações. A cada três segundos, um servidor consulta a lista de servidores ativos e pede a cada outro os registros que ainda não possui.

A requisição `sync` é enviada diretamente na porta 5560, com um resumo que informa a última sequência conhecida de cada origem. O servidor consultado devolve lotes de até 100 registros em MessagePack. O destinatário insere apenas os registros novos, usando o identificador único para evitar duplicações. Em cada ciclo podem ser recebidos vários lotes. Os dados também são armazenados nas tabelas de eventos e mensagens, permitindo listar canais e consultar o histórico.

Quando um servidor volta depois de uma parada, ele lê seu banco persistente e pede as operações ausentes aos outros. Como os volumes são separados, os servidores não compartilham o mesmo arquivo SQLite. Registros de uma versão anterior do banco são incorporados ao formato de replicação na primeira inicialização.

**O tipo de consistência é eventual.** Durante alguns segundos, um servidor pode não conhecer uma publicação ou canal criado no outro. Após a comunicação e a sincronização, as cópias convergem. Não há confirmação síncrona de todas as réplicas antes de responder ao cliente; portanto, esta implementação não oferece consistência forte nem garante que uma operação não replicada sobreviva à perda definitiva do disco do servidor de origem.

O projeto também aceita o pedido `history` com `channel` opcional, retornando as últimas 100 publicações registradas naquele servidor. Após a sincronização, ambos devem responder com o mesmo histórico.

## Teste de parada e recuperação

Com o sistema funcionando, abra outro terminal:

```sh
docker compose stop server1
```

Os bots continuarão publicando pelo `server2`. Depois:

```sh
docker compose start server1
docker compose logs -f server1 server2
```

Procure nos logs pelo evento `REPLICOU`, que mostra os registros recuperados. A volta do servidor não exige apagar seu volume. Para acompanhar eleição, procure `COORDENADOR_ELEITO` e `NOVO_COORDENADOR`.

## Testes disponíveis

Além dos testes com Docker, há testes da persistência e replicação:

```sh
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Foram verificados localmente a sintaxe Python e JavaScript, os testes automáticos de SQLite e uma integração com dois servidores Python, broker, proxy e referência. No teste de integração os dois bancos receberam os mesmos canais e mensagens; após a queda e retorno de um servidor, ele recuperou as publicações recebidas durante a parada. A execução completa com os dois bots JavaScript dentro do Docker ainda depende de um ambiente Docker funcional.

## Limitações

Este é um protótipo acadêmico. A eleição, os relógios e a replicação são implementações simplificadas para demonstrar os conceitos da disciplina. A replicação ocorre apenas entre servidores disponíveis, utiliza lotes periódicos e pode apresentar atraso temporário entre as cópias. Com mais de dois servidores, todos devem ter um nome válido na rede e configurar o mesmo serviço de referência, broker e proxy.

## Demonstração com três servidores

Com todos os serviços iniciados, execute em outro terminal:

```sh
docker compose ps
docker compose logs --tail=100 server1 server2 server3 | grep -E 'COORDENADOR_ELEITO|NOVO_COORDENADOR|AGUARDANDO_COORDENADOR'
```

O eleito deve aparecer nos logs como `COORDENADOR_ELEITO`. O rank é atribuído pela referência na ordem de cadastro; portanto, não assuma que `server3` será sempre eleito. Quando identificar o nome do coordenador, pare o serviço correspondente. Por exemplo, se `server3` foi eleito:

```sh
docker compose stop server3
docker compose logs -f --tail=30 server1 server2
```

Observe um novo evento `COORDENADOR_ELEITO` em um dos servidores restantes. Para restaurar o terceiro servidor:

```sh
docker compose start server3
```

A eleição e a replicação podem levar alguns segundos; como o sistema usa temporizadores e detecção periódica, não há troca instantânea garantida. Não use `docker compose down -v`, pois remove os volumes persistentes.
