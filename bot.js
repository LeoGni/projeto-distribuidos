const zmq = require('zeromq');
const {encode: empacotar, decode: desempacotar} = require('@msgpack/msgpack');
const crypto = require('node:crypto');

const nome = process.env.BOT_NAME || 'bot1';
const esperar = tempo => new Promise(resolver => setTimeout(resolver, tempo));
const horario = () => new Date().toISOString();
const inscritos = new Set();
const frases = ['Bom dia', 'Como voces estao?', 'Nova mensagem', 'Tudo certo por aqui', 'Ola pessoal'];
let relogio = 0;

function receberRelogio(dados) {
  if (dados && Number.isSafeInteger(dados.clock) && dados.clock >= 0) {
    relogio = Math.max(relogio, dados.clock);
  }
}

function enviarRelogio(dados) {
  relogio += 1;
  dados.clock = relogio;
  dados.sent_at = horario();
  return dados;
}

function mostrar(acao, dados) {
  console.log(`[${horario()}] ${nome} ${acao}: ${JSON.stringify(dados)}`);
}

async function pedir(acao, dados) {
  const conexao = new zmq.Request({receiveTimeout: 3500, sendTimeout: 3500, linger: 0});
  conexao.connect('tcp://broker:5555');
  const pedido = enviarRelogio({id: crypto.randomUUID(), action: acao, data: dados});
  try {
    mostrar('ENVIOU', pedido);
    await conexao.send(Buffer.from(empacotar(pedido)));
    const [mensagem] = await conexao.receive();
    const retorno = desempacotar(mensagem);
    receberRelogio(retorno);
    mostrar('RECEBEU', retorno);
    return retorno;
  } catch (erro) {
    mostrar('ERRO', {acao, mensagem: erro.message});
    return null;
  } finally {
    conexao.close();
  }
}

async function receber(conexao) {
  for await (const [topico, mensagem] of conexao) {
    try {
      const dados = desempacotar(mensagem);
      receberRelogio(dados);
      const canal = topico.toString();
      if (inscritos.has(canal)) {
        mostrar('PUBLICACAO_RECEBIDA', {
          canal, mensagem: dados.message, usuario: dados.username,
          enviado_em: dados.sent_at, recebido_em: horario(), relogio: relogio
        });
      }
    } catch (erro) {
      mostrar('ERRO_RECEBIMENTO', erro.message);
    }
  }
}

async function iniciar() {
  const conexao = new zmq.Subscriber();
  conexao.connect('tcp://pubproxy:5558');
  receber(conexao).catch(erro => mostrar('ERRO', erro.message));

  let conectado = false;
  while (!conectado) {
    const retorno = await pedir('login', {username: nome});
    conectado = retorno?.ok === true;
    if (!conectado) await esperar(1500);
  }

  while (true) {
    const retorno = await pedir('channels', {});
    let canais = retorno?.ok && Array.isArray(retorno.data?.channels) ? retorno.data.channels : [];

    if (retorno?.ok && canais.length < 5) {
      const canal = `canal_${crypto.randomBytes(3).toString('hex')}`;
      const criado = await pedir('create_channel', {username: nome, channel: canal});
      if (criado?.ok) canais.push(canal);
    }

    const disponiveis = canais.filter(canal => !inscritos.has(canal));
    if (inscritos.size < 3 && disponiveis.length > 0) {
      const canal = disponiveis[crypto.randomInt(disponiveis.length)];
      conexao.subscribe(canal);
      inscritos.add(canal);
      mostrar('INSCREVEU', {canal, enviado_em: horario()});
      await esperar(300);
    }

    if (canais.length === 0) {
      await esperar(1500);
      continue;
    }

    const canal = canais[crypto.randomInt(canais.length)];
    for (let i = 0; i < 10; i++) {
      const frase = frases[crypto.randomInt(frases.length)];
      await pedir('publish', {username: nome, channel: canal, message: `${frase} ${crypto.randomInt(10000)}`});
      await esperar(1000);
    }
  }
}

iniciar().catch(erro => {
  mostrar('ERRO', erro.message);
  process.exit(1);
});
