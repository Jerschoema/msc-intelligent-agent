# Academic Research Agent

## Purpose

This is a LLM-powered, multi-agent research system. You give it a topic (and
optionally a research question and a minimum number of sources and words),
and it autonomously searches multiple academic databases, decides which
papers are worth fetching, parses them, ranks their reputation, summarises
them with cited claims, and publishes a Markdown and PDF research brief.
Everything runs locally on a small Ollama model, so there are no API keys required or any costs involved.

This is the Unit 11 implementation of the Unit 6 design proposal


## High-level overview

Our design is a supervisor architecture built around a blackboard knowledge
hub for multi-agent communication. We model academic research as a
sequential pipeline.

The central insight is that research is structured, but our understanding
of the topic evolves incrementally. Subtopics, claims and perspectives are
not known up front, they emerge from the sources themselves. The supervisor handles convergence.

One pass of the pipeline runs:

```
START -> research -> parse -> summarise -> rank -> index -> discover ->
converge -> (retry back to research) OR (publish) -> END
```

- Researcher finds and downloads sources, and posts them to the blackboard.
- Parser inspects each document and picks the best extraction tool.
- Summariser writes a summary, extracts up to 4 claims with evidence, and
  judges whether the source is on topic.
- Ranking assigns a reputation tier with a justification.
- Index stores everything, with metadata, in the vector database.
- Discovery mines each source for new keywords and topics.
- Supervisor's converge step decides to retry, sending the new leads back
  to the researcher, or to publish.


Every tool call, decision and justification is posted to a blackboard
(SQLite), so a run is fully auditable afterwards.

## Installation

Requires Python 3.11 or higher and [Ollama](https://ollama.com) running
locally.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
ollama pull qwen3:4b
```

The model needs to support tool calling. `qwen3:4b` has been used to test the application. The Gemma family does not support tools and will not work.

There is a deep mode and a fast mode. The deep mode will take hours. The fast mode also might take up to 2 hours. 

State the topic, the research question, and the minimum sources and words,
all in one line. Anything you leave out is asked for interactively (or
defaulted, when not running in a terminal):

## Usage

```bash
python main.py "federated learning for medical imaging — what are the privacy risks? minimum 5 reputable sources and 800 words"
```


```bash
python main.py "transformer models for time series forecasting"  
python main.py --deep "..."   
```

The brief is written to `data/reports/<run_id>-<topic>.md/pdf`
The blackboard is at `data/blackboard.db`; 
The vector store at `data/chroma/`.

