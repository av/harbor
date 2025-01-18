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
harbor ollama create -f hargent.Modelfile hargent
```