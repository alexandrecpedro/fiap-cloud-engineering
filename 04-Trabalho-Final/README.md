# 04 - Trabalho Final: Modernizando a ingestão da PedeJá (EFS → S3 → Lambda → API)

**Antes de começar, execute os passos abaixo para configurar o ambiente caso não tenha feito isso ainda na aula de HOJE: [Preparando Credenciais](../01-create-codespaces/Inicio-de-aula.md)**

Os comandos deste trabalho rodam em **dois ambientes**: o provisionamento e a maior parte no **terminal do GitHub Codespaces**; a migração (Bloco 1) dentro da **instância EC2** que você acessa via SSM. Cada passo sinaliza onde executar.

> [!WARNING]
> **Pré-requisitos — confira antes de começar:**
>
> - [ ] Você já executou as 4 demos (Storage, x86/Graviton, ECS/Fargate, Lambda). Este trabalho **monta blocos** dessas demos.
> - [ ] Codespace aberto e sincronizado com credenciais da AWS Academy (rodou o [Preparando Credenciais](../01-create-codespaces/Inicio-de-aula.md) na aula de hoje).
> - [ ] `aws sts get-caller-identity` retorna um `Account` e um `Arn` sem erro.
> - [ ] `aws s3 ls | grep base-config-` lista exatamente **um** bucket do seu RM.
> - [ ] `terraform -version` retorna >= 1.3.
>
> **O que você vai fazer:** modernizar a ingestão de pedidos da PedeJá em três blocos — **migrar** os arquivos do EFS legado para o S3, **processar** com uma Lambda Graviton que agrega o faturamento, e **servir** o resultado por uma API. A infraestrutura (Terraform) vem **pronta**; você completa o **miolo** de duas Lambdas e escreve a decisão de arquitetura. **Tempo estimado: 2 horas** (execução ~40 min + tempo para completar o código, observar, tirar prints e escrever o `DECISION.md`).

Você é o engenheiro de dados da **PedeJá**. Os pedidos hoje vivem num **servidor de arquivos legado (EFS)** — um arquivo `.json` por pedido, como o sistema antigo gravava. A **Marina, líder de Dados**, quer modernizar: tirar os dados do file system, colocá-los no **data lake (S3)**, e disponibilizar um **resumo de faturamento por cidade** através de uma **API**. Você vai construir exatamente essa jornada, reaproveitando tudo que praticou nas demos.

## Principais pontos de aprendizagem

- Migrar dados de **file storage (EFS)** para **object storage (S3)** e por que essa é a direção certa para um data lake analítico.
- Completar o **miolo** de uma Lambda de processamento (ler S3 → agregar → gravar), com observabilidade via Powertools — como na demo de Lambda.
- Aplicar na prática a decisão **x86 vs Graviton**: a Lambda roda em `arm64` e você justifica por quê.
- Expor dados do S3 por uma **API (Lambda + API Gateway)** e decidir, com argumento, **Lambda vs. Fargate**.
- Amarrar as quatro demos numa única solução end-to-end e defender as escolhas num documento estilo ADR.

## O que você terá ao final

Uma pipeline funcionando de ponta a ponta — pedidos migrados do EFS para o S3, processados por uma Lambda Graviton e servidos por uma API HTTP — mais um `DECISION.md` defendendo suas escolhas de arquitetura. A entrega é um **zip** com o código que você completou, o `DECISION.md` e os prints que provam a execução.

> [!TIP]
> Ao longo do trabalho você vai encontrar blocos `<details><summary>💡 Clique para entender</summary>`. Eles aprofundam o "porquê". Se estiver com pressa, **pule**.

## Mapa do trabalho

| # | Bloco | O que acontece | Passos | Tempo |
|---|-------|---------------|--------|-------|
| 0 | [Provisionar (entregue pronto)](#bloco-0---provisionar-a-infraestrutura) | Um script sobe VPC + EC2 + EFS (com os pedidos) + S3 + as 2 Lambdas + API. | [1](#passo-1) · [2](#passo-2) | ~10 min |
| 1 | [Migrar EFS → S3](#bloco-1---migrar-os-pedidos-do-efs-para-o-s3) | Entra na EC2 via SSM e sincroniza os pedidos do file system para o data lake. | [3](#passo-3) · [4](#passo-4) · [5](#passo-5) | ~15 min |
| 2 | [Processar (você completa)](#bloco-2---processar-o-faturamento-lambda-graviton) | Completa o miolo da Lambda Graviton que agrega faturamento por cidade. | [6](#passo-6) · [7](#passo-7) · [8](#passo-8) | ~30 min |
| 3 | [Servir (você completa)](#bloco-3---servir-o-resultado-por-uma-api) | Completa a Lambda da API que lê o resumo do S3 e responde em JSON. | [9](#passo-9) · [10](#passo-10) · [11](#passo-11) | ~25 min |
| 4 | [Decidir e entregar](#bloco-4---decidir-e-entregar) | Escreve o `DECISION.md`, monta o zip com código + prints e destrói a infra. | [12](#passo-12) · [13](#passo-13) · [14](#passo-14) | ~30 min |

> Os passos são numerados de 1 a 14, contínuos. Se travar, clique no número no mapa para ir direto ao passo.

<details>
<summary><b>💡 Como este trabalho reaproveita cada demo (abra para ver o mapa mental)</b></summary>
<blockquote>

| Demo que você fez | Como aparece aqui |
|-------------------|-------------------|
| **02.1 Storage (EFS + S3)** | O Bloco 1 é a migração `EFS → S3`. A decisão "por que S3 e não EFS" está no `DECISION.md`. |
| **03.1 x86 vs Graviton** | As Lambdas rodam em `arm64` (Graviton). Você justifica a escolha com o que mediu na demo. |
| **03.2 ECS + Fargate** | Entra na decisão "por que Lambda e não Fargate para servir a API". |
| **03.3 Lambda (fase 1)** | O padrão API Gateway → Lambda → S3 e a observabilidade com Powertools são reaproveitados direto. |

O que **não** entra: SQS e Kinesis (fases 2 e 3 da demo de Lambda). Este trabalho para na ingestão direta com Lambda.

</blockquote>
</details>

## Contexto

Nas quatro demos você viu, separadamente, storage, três modelos de compute e observabilidade. Um sistema real não usa essas peças isoladas — ele as **combina** para resolver um problema de negócio. Este trabalho é essa combinação: uma pequena modernização de dados, do tipo que um engenheiro faz na primeira semana de emprego, montando peças que já existem e escrevendo só o miolo que falta.

---

## Bloco 0 - Provisionar a infraestrutura

> *Marina: "Não perca tempo montando encanamento. O time de plataforma já deixou a base pronta — foca no que resolve o problema."*

Toda a infraestrutura vem pronta: VPC, a EC2 com o EFS legado (já com os 10 pedidos dentro), o bucket S3 do data lake, as duas Lambdas e a API Gateway. Você roda **um** script e espera.

### Resultado esperado deste bloco

Um comando imprime `BUCKET`, `INSTANCE_ID` e `API_URL`. A partir daí, toda a infra existe na sua conta e você pode começar o trabalho de verdade.

<a id="passo-1"></a>
**1.** No Codespaces, entre na pasta do trabalho e rode o script de provisionamento. Ele descobre o bucket de estado sozinho, inicializa e aplica os 3 stacks Terraform na ordem certa:

```bash
cd /workspaces/fiap-cloud-engineering/04-Trabalho-Final
bash scripts/init.sh
```

O script leva ~8-10 min (a EC2 e o EFS demoram para subir). Ao final, ele imprime três linhas:

```
BUCKET=pedeja-datalake-<sua-conta>
INSTANCE_ID=i-0abc123...
API_URL=https://xxxx.execute-api.us-east-1.amazonaws.com
```

<!-- PRINT SUGERIDO: img/tf-init.png
     Terminal mostrando as 3 linhas finais (BUCKET, INSTANCE_ID, API_URL) do init.sh. -->
![](img/tf-init.png)

<details>
<summary><b>⚠ Se der erro: <code>nenhum bucket base-config- encontrado</code></b></summary>
<blockquote>
O setup de credenciais da aula não foi executado. Volte ao [Preparando Credenciais](../01-create-codespaces/Inicio-de-aula.md), puxe credenciais novas e rode o passo 1 de novo.
</blockquote>
</details>

<a id="passo-2"></a>
**2.** Capture os três valores em variáveis de ambiente — os próximos blocos usam `$BUCKET`, `$INSTANCE_ID` e `$API`. Rode na pasta `04-Trabalho-Final`:

```bash
cd /workspaces/fiap-cloud-engineering/04-Trabalho-Final
export BUCKET=$(terraform -chdir=terraform/01-storage output -raw bucket_datalake)
export INSTANCE_ID=$(terraform -chdir=terraform/01-storage output -raw instance_id)
export API=$(terraform -chdir=terraform/03-api output -raw api_url)
echo "BUCKET......: $BUCKET"
echo "INSTANCE_ID.: $INSTANCE_ID"
echo "API.........: $API"
```

> [!TIP]
> Essas variáveis valem enquanto o terminal estiver aberto. Se fechar ou abrir outro terminal, rode o passo 2 de novo.

Confirme que as duas Lambdas subiram (sanidade do provisionamento):

```bash
aws lambda list-functions \
  --query "Functions[?starts_with(FunctionName,'pedeja-')].FunctionName" --output text
```

Saída esperada: `pedeja-processa-faturamento    pedeja-api-faturamento` (em qualquer ordem). Se faltar alguma, algum stack não aplicou — rode `bash scripts/init.sh` de novo (é idempotente).

### Checkpoint

- [x] `init.sh` terminou imprimindo `BUCKET`, `INSTANCE_ID` e `API_URL`.
- [x] As três variáveis de ambiente estão preenchidas (passo 2).

---

## Bloco 1 - Migrar os pedidos do EFS para o S3

> *Marina: "Primeiro, tira esses pedidos do servidor de arquivos antigo e joga no nosso data lake no S3."*

Os 10 pedidos estão como arquivos `.json` no EFS montado em `/efs/pedidos` dentro da EC2. Você vai entrar na instância via SSM e sincronizar para o S3 — o mesmo tipo de operação de storage que você viu na demo 02.1.

### Resultado esperado deste bloco

Os 10 arquivos de pedido copiados do EFS para `s3://$BUCKET/raw/`.

<a id="passo-3"></a>
**3.** Abra a sessão na EC2 pelo console. Acesse o [console do EC2](https://us-east-1.console.aws.amazon.com/ec2/home?region=us-east-1#Instances:instanceState=running), selecione a instância `pedeja-migracao-instance`, clique em `Conectar`, aba `Gerenciador de sessões`, botão `Conectar`. Uma nova aba abre com o terminal da EC2.

> [!NOTE]
> Diferente da demo de Storage, aqui você **não precisa** configurar o log group `/ssm/ssh` nem as preferências do Session Manager — este trabalho não audita a sessão. Conecte direto.

<!-- PRINT SUGERIDO: img/ssm-conectar.png
     Aba "Gerenciador de sessões" com a pedeja-migracao-instance selecionada e o botão Conectar. -->
![](img/ssm-conectar.png)

<a id="passo-4"></a>
**4.** **Dentro da sessão SSM da EC2** (não no Codespaces — é outro terminal), confira que os pedidos já foram plantados no EFS. Este é o **go/no-go** de entrada: a EC2 planta os 10 pedidos ao subir (via `user-data`), e isso leva ~1-2 min **depois** do `init.sh` terminar. Rode:

```bash
ls /efs/pedidos/ | wc -l
```

Saída esperada: `10`. Se vier `0` ou `No such file or directory`, o `user-data` ainda está rodando — **espere ~1 min e rode de novo** até dar 10 antes de seguir.

<details>
<summary><b>⚠ Se der erro: <code>ls: /efs/pedidos: No such file or directory</code> mesmo após 3 min</b></summary>
<blockquote>

O mount do EFS ou a cópia dos pedidos falhou no boot. Monte e replante manualmente na sessão SSM:

```bash
FS_ID=$(aws efs describe-file-systems --query "FileSystems[?Name=='pedeja-efs-legado'].FileSystemId" --output text --region us-east-1)
sudo mkdir -p /efs && sudo mount -t efs ${FS_ID}:/ /efs
ls /efs/pedidos/ | wc -l
```

Se ainda assim vier `0`, o `user-data` falhou — destrua e recrie o stack 01 (`terraform -chdir=terraform/01-storage apply -replace` não resolve o boot; use `destroy` + `init.sh`).

</blockquote>
</details>

<a id="passo-5"></a>
**5.** **Ainda na sessão SSM da EC2**, migre os pedidos do EFS legado para o data lake S3. O bucket é sempre `pedeja-datalake-<sua-conta>` — o comando monta o nome sozinho (a variável do passo 2 não existe aqui, pois este é outro terminal):

```bash
BUCKET="pedeja-datalake-$(aws sts get-caller-identity --query Account --output text)"
aws s3 sync /efs/pedidos s3://$BUCKET/raw/ --region us-east-1
aws s3 ls s3://$BUCKET/raw/ --region us-east-1 | wc -l
```

Saída esperada: 10 linhas `upload: ... to s3://.../raw/PED-000X.json`, e ao final `10` (o **go/no-go** da migração). Se não deu 10, espere alguns segundos e rode o `sync` de novo.

<!-- PRINT SUGERIDO: img/migracao.png
     Saída do aws s3 sync mostrando os 10 uploads para raw/ e o "10" final. -->
![](img/migracao.png)

<details>
<summary><b>💡 Clique para entender — por que <code>aws s3 sync</code> e não copiar pelo laptop</b></summary>
<blockquote>

O `aws s3 sync` roda **de dentro da EC2**, que já enxerga o EFS montado e tem permissão S3 pela `LabInstanceProfile`. Os bytes vão direto da rede AWS para o S3, sem passar pela sua máquina. É a mesma lição da demo de Storage: mantenha o dado perto de onde ele é processado, não force um round-trip pelo cliente.

O `sync` também é **idempotente** — se você rodar de novo, ele só copia o que mudou. Rodar duas vezes não duplica nada.

</blockquote>
</details>

### Checkpoint

- [x] `ls /efs/pedidos/ | wc -l` retornou 10 (os pedidos foram plantados no EFS legado).
- [x] `aws s3 ls s3://$BUCKET/raw/ | wc -l` retornou 10 (migração concluída).

---

## Bloco 2 - Processar o faturamento (Lambda Graviton)

> *Marina: "Agora transforma esses pedidos crus num resumo de faturamento por cidade."*

A Lambda `pedeja-processa-faturamento` já existe (o Bloco 0 criou), roda em **Graviton (arm64)** e tem toda a leitura/escrita do S3 pronta. **Falta só o miolo**: a lógica que agrega o faturamento por cidade. É o que você vai completar.

### Resultado esperado deste bloco

O arquivo `resumo/faturamento.json` gravado no S3, com o faturamento por cidade batendo o número determinístico dos 10 pedidos.

<a id="passo-6"></a>
**6.** Abra o handler da Lambda de processamento no editor do Codespaces:

```bash
code /workspaces/fiap-cloud-engineering/04-Trabalho-Final/lambdas/processa/handler.py
```

Leia o arquivo inteiro. Tudo está pronto — imports, Powertools, `ler_pedidos_do_s3()` e `gravar_resumo_no_s3()` — **exceto** o bloco marcado com `# TODO — VOCE COMPLETA AQUI`.

<a id="passo-7"></a>
**7.** Complete o `TODO`: a partir da lista `pedidos` (cada item tem `cidade` e `valor`), monte o dicionário `resumo` agregando faturamento e contagem por cidade, no formato indicado no comentário. São poucas linhas de Python — a demo de Lambda já mostrou o padrão de somar por dimensão.

> [!TIP]
> O resultado precisa ser determinístico: os 10 pedidos são fixos, então o faturamento por cidade é sempre o mesmo. Você valida contra o número conhecido no passo 8. Se der diferente, o bug está na sua agregação.

<a id="passo-8"></a>
**8.** Reaplique **só o stack da Lambda de processamento** e invoque a função. O `terraform apply` reempacota o `handler.py` (o hash do zip muda quando você edita o código) e atualiza a Lambda:

```bash
cd /workspaces/fiap-cloud-engineering/04-Trabalho-Final
terraform -chdir=terraform/02-processa apply -auto-approve
aws lambda invoke --function-name pedeja-processa-faturamento \
  --cli-binary-format raw-in-base64-out --payload '{}' /tmp/saida.json
cat /tmp/saida.json && echo
aws s3 cp s3://$BUCKET/resumo/faturamento.json -
```

Saída esperada da invocação: `{"status": "ok", "cidades": 4, "s3_key": "resumo/faturamento.json"}`.

> [!NOTE]
> Se o `apply` disser **`No changes`** mas você editou o código, force o reempacotamento apagando o zip antigo e reaplicando:
> ```bash
> rm -f terraform/02-processa/build/processa.zip
> terraform -chdir=terraform/02-processa apply -auto-approve
> ```

O `resumo/faturamento.json` deve conter (o faturamento é determinístico — **tem que bater**). As cidades aparecem **sem acento**, exatamente como vêm no dataset (`Sao Paulo`) — sua saída deve ser idêntica a esta:

| Cidade | Pedidos | Faturamento |
|--------|---------|-------------|
| Sao Paulo | 4 | 235.3 |
| Rio de Janeiro | 2 | 198.4 |
| Curitiba | 2 | 90.0 |
| Belo Horizonte | 2 | 73.0 |
| **Total** | **10** | **596.7** |

<!-- PRINT SUGERIDO: img/processa.png
     Terminal mostrando o resultado da invocação e o conteúdo do faturamento.json com os 4 valores. -->
![](img/processa.png)

Confirme que a Lambda roda mesmo em **Graviton** — é uma das decisões que você defende no `DECISION.md`:

```bash
aws lambda get-function-configuration --function-name pedeja-processa-faturamento \
  --query "Architectures" --output text
```

Saída esperada: `arm64`.

<details>
<summary><b>⚠ Se der erro: o faturamento não bate ou vem <code>cidades: 0</code></b></summary>
<blockquote>

- `cidades: 0` → seu `resumo` ficou vazio. Confirme que você percorreu `pedidos` e preencheu o dicionário no formato do comentário.
- Faturamento errado → cheque se está somando `p["valor"]` (e não contando) e arredondando com `round(x, 2)`.
- `KeyError` → confirme que usou as chaves `"cidade"` e `"valor"` (é assim que cada pedido vem).
- `apply` disse `No changes` → use o bloco `rm -f ...build/processa.zip` do `[!NOTE]` acima e reaplique.

Depois de corrigir, rode o passo 8 de novo.

</blockquote>
</details>

### Checkpoint

- [x] Você completou o `TODO` do `lambdas/processa/handler.py`.
- [x] A invocação retornou `status: ok` e `cidades: 4`.
- [x] `get-function-configuration` confirmou `arm64` (Graviton).
- [x] O `faturamento.json` no S3 bate o total de **R$ 596,70** em 10 pedidos.

---

## Bloco 3 - Servir o resultado por uma API

> *Marina: "Perfeito. Agora me dá um jeito de consultar isso sem entrar na AWS — uma URL que devolve o faturamento."*

A API já existe: API Gateway → Lambda `pedeja-api-faturamento`. A resposta HTTP e o roteamento estão prontos. **Falta o miolo**: ler o `resumo/faturamento.json` do S3 e devolvê-lo. Você completa.

### Resultado esperado deste bloco

`GET {API}/faturamento` retorna o JSON do faturamento por cidade.

<a id="passo-9"></a>
**9.** Abra o handler da API:

```bash
code /workspaces/fiap-cloud-engineering/04-Trabalho-Final/lambdas/api/handler.py
```

Está tudo pronto — a função `resposta()` e o roteamento — **exceto** o bloco `# TODO — VOCE COMPLETA AQUI`.

<a id="passo-10"></a>
**10.** Complete o `TODO`: leia o objeto `CHAVE_RESUMO` do bucket no S3 e faça o `json.loads` para o dict `faturamento`. Trate o caso do objeto ainda não existir devolvendo `resposta(404, ...)`. O comentário no código dá a dica do `boto3`.

<a id="passo-11"></a>
**11.** Reaplique **só o stack da API** (reempacota seu código) e consulte o endpoint:

```bash
cd /workspaces/fiap-cloud-engineering/04-Trabalho-Final
terraform -chdir=terraform/03-api apply -auto-approve
curl -s "$API/faturamento" | python3 -m json.tool
```

Saída esperada: o mesmo JSON de faturamento por cidade do passo 8 (as **4 cidades**, total R$ 596,70), agora servido pela API.

> [!IMPORTANT]
> Se o `curl` retornar `{}` (vazio) com sucesso, **não terminou**: significa que o `resumo/faturamento.json` está vazio — seu TODO do **bloco 2** (passo 7) não agregou nada. Volte ao passo 8, confirme que a invocação deu `cidades: 4`, e só então consulte a API. Um `{}` não é a resposta certa.

> [!NOTE]
> Se o `apply` disser **`No changes`** mas você editou o handler, force o reempacotamento: `rm -f terraform/03-api/build/api.zip && terraform -chdir=terraform/03-api apply -auto-approve`.

<!-- PRINT SUGERIDO: img/api.png
     Terminal mostrando o curl para $API/faturamento e o JSON de faturamento por cidade retornado. -->
![](img/api.png)

<details>
<summary><b>⚠ Se der erro: <code>{"erro": "resumo ainda nao gerado"}</code> (404)</b></summary>
<blockquote>
A API funcionou, mas o `resumo/faturamento.json` não existe no S3 — você provavelmente pulou ou errou o Bloco 2. Volte ao passo 8, gere o resumo, e consulte a API de novo.
</blockquote>
</details>

### Checkpoint

- [x] Você completou o `TODO` do `lambdas/api/handler.py`.
- [x] `curl $API/faturamento` retorna o faturamento por cidade em JSON.

---

## Bloco 4 - Decidir e entregar

> *Marina: "Antes de fechar: me explica por que você escolheu essa arquitetura. Vou levar para a diretoria."*

### Resultado esperado deste bloco

Um `DECISION.md` preenchido, o zip de entrega montado, e a infra destruída.

<a id="passo-12"></a>
**12.** Copie o template e responda cada seção com base no que você **mediu e viu nas demos** — é o mais importante da entrega:

```bash
cd /workspaces/fiap-cloud-engineering/04-Trabalho-Final
cp DECISION.md.template DECISION.md
code DECISION.md
```

O `DECISION.md` te pede para defender: **S3 vs EFS**, **Graviton**, **Lambda vs Fargate** e as consequências. Poucas linhas por seção, mas com o **porquê** — é o que separa júnior de sênior.

<a id="passo-13"></a>
**13.** Monte o **zip de entrega** com o código que você completou, o `DECISION.md` e os prints que tirou ao longo do caminho. Coloque seus prints numa pasta `prints/` antes de compactar:

```bash
cd /workspaces/fiap-cloud-engineering/04-Trabalho-Final
mkdir -p entrega/prints
# Os dois handlers se chamam handler.py — renomeie ao copiar para nao colidir:
cp lambdas/processa/handler.py entrega/processa_handler.py
cp lambdas/api/handler.py      entrega/api_handler.py
cp DECISION.md entrega/
# copie para entrega/prints/ os prints que voce salvou (migracao, processa, api)
zip -r trabalho-final.zip entrega/
```

A estrutura do zip deve ficar assim:

```
entrega/
├── processa_handler.py   (bloco 2 — com seu miolo de agregacao)
├── api_handler.py        (bloco 3 — com seu miolo de leitura do S3)
├── DECISION.md
└── prints/
    ├── migracao.png
    ├── processa.png
    └── api.png
```

<a id="passo-14"></a>
**14.** Destrua toda a infraestrutura. **Este passo não é opcional.**

```bash
cd /workspaces/fiap-cloud-engineering/04-Trabalho-Final
terraform -chdir=terraform/03-api destroy -auto-approve
terraform -chdir=terraform/02-processa destroy -auto-approve
terraform -chdir=terraform/01-storage destroy -auto-approve
```

> [!CAUTION]
> A EC2, o EFS e as Lambdas geram custo enquanto vivos. A ordem de destruição é a **inversa** da criação (api → processa → storage), porque o storage cria o bucket que os outros usam. Destrua sempre no fim.

### Checkpoint

- [x] `DECISION.md` preenchido com as 4 decisões defendidas.
- [x] `trabalho-final.zip` montado com código + `DECISION.md` + prints.
- [x] Os 3 stacks destruídos (`Destroy complete!` em cada um).

---

## Conclusão

Você modernizou a ingestão da PedeJá de ponta a ponta: migrou os pedidos de um **file system legado (EFS)** para o **data lake (S3)**, processou-os com uma **Lambda em Graviton** que agrega o faturamento, e serviu o resultado por uma **API (Lambda + API Gateway)** — completando apenas o miolo de cada peça e defendendo cada escolha num documento de decisão. Mais do que os serviços, você praticou o que um engenheiro de dados faz de verdade: **combinar peças conhecidas para resolver um problema de negócio** e justificar a arquitetura com dados, não com opinião.

---

<details>
<summary><b>💡 Glossário rápido</b></summary>
<blockquote>

| Termo | O que é |
|-------|---------|
| EFS | Elastic File System — NFS gerenciado; aqui, o "file server legado" da PedeJá. |
| S3 | Object storage; o data lake destino da migração. |
| `aws s3 sync` | Copia incremental e idempotente de arquivos para o S3. |
| Graviton (arm64) | CPUs ARM da AWS; ~20% mais baratas, escolhidas para as Lambdas. |
| Lambda | Função serverless invocada por evento (aqui: invocação direta e via API Gateway). |
| API Gateway | Porta de entrada HTTP que entrega a requisição como evento à Lambda. |
| Powertools | Biblioteca AWS para Lambda: log estruturado, métricas EMF, trace X-Ray. |
| LabInstanceProfile | Perfil de instância do Academy que dá à EC2 acesso a SSM e S3. |
| LabRole | Role IAM pré-criada do Academy usada pelas Lambdas. |

</blockquote>
</details>

<details>
<summary><b>💡 Como pedir ajuda se travou</b></summary>
<blockquote>

**Antes de abrir issue ou chamar o professor, colete:**

1. Em qual passo (número) travou.
2. A mensagem de erro **literal** (copie e cole, não resuma).
3. O que `aws sts get-caller-identity` retorna agora.
4. Em qual ambiente o erro apareceu (Codespaces ou sessão SSM da EC2).

**Canais, em ordem:**

1. [Issues deste repositório](https://github.com/vamperst/fiap-cloud-engineering/issues) — preferido, cria histórico pesquisável.
2. Email do professor com os 4 itens acima.
3. Na sala de aula, durante o laboratório.

</blockquote>
</details>
