### Modelfiles

This folder contains Ollama Modelfiles that are distributed alongside Harbor.
See [Custom Modelfiles](../../docs/2.2.1-Backend:-Ollama#custom-modelfiles) guide for information on importing these.

TLDR:

```bash
# Move to the modelfiles directory
cd $(harbor home)/ollama/modelfiles

# Import
harbor ollama create -f <modelfile> <model name>
```

### Snippets

```bash
# hargent
harbor ollama create -f hargent.Modelfile hargent

# Gemma 3 QAT w/ Tools
harbor ollama create -f gemma3-qat-tools.Modelfile gemma-3:4b-qat
```