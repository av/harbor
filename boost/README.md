> Handle: `boost`
> URL: [http://localhost:34131/](http://localhost:34131/)

![Screenshot of boost bench](./boost.png)
<small>`g1` and `rcn` optimizer modules compared to original LLMs. [BBH256](https://gist.github.com/av/18cc8138a0acbe1b30f51e8bb19add90) task, run with [Harbor Bench](./5.1.-Harbor-Bench)</small>

`boost` is a service that acts as an optimizing LLM proxy. It takes your inputs, and pre-processes them before sending them to the downstream API.

Features that make Harbor's `boost` special:
- 🥇 First-class support for streaming completions
- 🗣️ `boost` modules can provide intermediate output, like status messages or internal monologue
- 🎭 `boost` can serve as a plain LLM proxy (multiple downstream APIs behind a single endpoint)
- ✍️ `boost` is scriptable, you can write your own modules

The main focus, of course are the workflows that can help improve the LLM output in specific scenarios. Here are some examples of what's possible with `boost`:
- When "random" is mentioned in the message, `klmbr` will rewrite 35% of message characters to increase the entropy and produce more diverse completion
- Launch self-reflection reasoning chain when the message ends with a question mark
- Expand the conversation context with the "inner monologue" of the model, where it can iterate over your question a few times before giving the final answer
- Apply a specific LLM personality if the message contains a specific keyword

Moreover, boost is scriptable, you can provision your own modules with the workflows suitable for your needs. See [Custom Modules](#custom-modules) section for more information.

`boost` operates at the OpenAI-compatible API level, so can be used with any LLM backend that accepts OpenAI API requests. You can also plug `boost` into the UIs that are compatible with OpenAI API.

> [!IMPORTANT]
> You don't have to use Harbor to run `boost`. See the [Standalone Usage section](#standalone-usage) for more information.

---

### Table of Contents

- [Starting](#starting)
- [Configuration](#configuration)
  - [Boost configuration](#boost-configuration)
- [Modules](#boost-modules--configuration)
  - [`klmbr` - boost llm creativity](#klmbr---boost-llm-creativity)
  - [`rcn` - recursive certainty validation](#rcn---recursive-certainty-validation)
  - [`g1` - o1-like reasoning chains](#g1---o1-like-reasoning-chains)
  - [`mcts` - Monte Carlo Tree Search](#mcts---monte-carlo-tree-search)
  - [`eli5` - Explain Like I'm 5](#eli5---explain-like-im-5)
  - [`supersummer` - Super Summarization](#supersummer---super-summarization)
  - Custom Modules (not configurable, mostly examples, but can still be enabled)
    - [discussurl](https://github.com/av/harbor/blob/main/boost/src/custom_modules/discussurl.py) - parse mentioned URLs and add them to the context
    - [meow](https://github.com/av/harbor/blob/main/boost/src/custom_modules/meow.py) - the model ignores all previous instructions and just meows
    - [unstable](https://github.com/av/harbor/blob/main/boost/src/custom_modules/unstable.py) - a random personality is generated for every response, model is asked to follow it
- [API](#api)
- [Custom Modules](#custom-modules)


### Starting

```bash
# [Optional] pre-build the image
harbor build boost

# Start the service
harbor up boost
```

`boost` is automatically connected to the LLM backends integrated with Harbor. It has its own API which will serve "boosted" models.

```bash
# Get the URL for the boost service
harbor url boost

# Open default boost enpdoint in the browser
harbor open boost
```

When running with Harbor's Open WebUI, "boosted" models will be available there automatically.

### Configuration

Configuration is done via the Harbor CLI, [`harbor config`](./3.-Harbor-CLI-Reference#harbor-config) or the `.env` file. All three ways are interchangeable, you can read more about them in the [User Guide](1.-Harbor-User-Guide#configuring-services).

```bash
# Enable/Disable a module
harbor boost modules add <module>
harbor boost modules rm <module>

# Set a parameter
harbor boost <module> <parameter>
harbor boost <module> <parameter> <value>

# See boost/module help entries
# for more info
harbor boost --help
harbor boost klmbr --help
harbor boost rcn --help
harbor boost g1 --help
```

#### Boost configuration

You can adjust certain aspects of the `boost` service that are shared between all the modules. This includes the API behavior and specifics of the module execution. Please find supported configuration options below.

```bash
# Adjust the port that Boost will linked to on the host
harbor config set boost.host.port 34131

# Additional OpenAI-compatible APIs to boost
harbor boost urls add http://localhost:11434/v1
harbor boost urls rm http://localhost:11434/v1
harbor boost urls rm 0 # by index
harobr boost urls ls

# Keys for the OpenAI-compatible APIs to boost. Semicolon-separated list.
# ⚠️ These are index-matched with the URLs. Even if the API doesn't require a key,
# you still need to provide a placeholder for it.
harbor boost keys add sk-ollama
harbor boost keys rm sk-ollama
harbor boost keys rm 0 # by index
harbor boost keys ls
```

Below are additional configuration options that do not have an alias in the Harbor CLI (so you need to use [`harbor config`](./3.-Harbor-CLI-Reference#harbor-config) directly). For example `harbor config set boost.intermediate_output true`.

**`boost.api.key`**

By default, boost will accept and serve any request, but you can configure one or more API keys to restrict access to the service.

```bash
# Configure the API key
harbor config set boost.api.key sk-boost
# Send the API key in the header
# Authorization: sk-boost

# You can specify multiple keys as well
# note "keys" instead of "key", and semicolon-separated list
harbor config set boost.api.keys sk-user1;sk-user2;sk-user3
```

**`boost.intermediate_output`**

When set to `true`, the boost output the intermediate steps of the module, not only the final result, providing more dynamic feedback to the user.

Intermediate output includes status messages, internal monologue, and other non-final completions. Note that it doesn't mean "all output" from the module, as the module source can still decide to not emit specific things at all, or inverse - emit them even if this setting is off.

Example of the intermediate output from the `g1` module - underlying reasoning steps:

![example of intermediate output from g1 boost module](g1-reasoning.png)

**`boost.status.style`**

A module can call `llm.emit_status` during its processing, which will be streamed as a "status" or "progress" message to the user. This setting controls the format of this message, which will be dependent on what's supported by the frontend where boost response is displayed.

Options:
```bash
md:codeblock "\n```boost\n{status}\n```\n",
md:h1        "\n\n# {status}\n\n",
md:h2        "\n\n## {status}\n\n",
md:h3        "\n\n### {status}\n\n",
plain        "\n\n{status}\n\n",
none         ""
```

The default is `md:codeblock` and looks like this in the WebUI:

![screenshot of status in the webui](webui-boost-status.png)

**`boost.base_models`**

Depending on the configuration of your setup, your LLM backend might or might not be connected to the UI directly. If not (or using boost as a standalone service), you can toggle this option on for the `boost` to serve them as is.

```bash
# Now "unboosted" models will also be available
# via the boost API
harbor config boost.base_models true
```

**`boost.model_filter`**

When specified, `boost` will only serve models matching the filter. The filter is a key/value expression that'll be matched against the model metadata. See examples below:

```bash
# Only boost models with the "llama" in the name
harbor config set boost.model_filter id.contains=llama
# Only boost models matching the regex
harbor config set boost.model_filter id.regex=.+q8_0$
# Boost by regex matching multiple IDs
harbor config set boost.model_filter "id.regex=.*(llama3.1:8b|llama3.2:3b|qwen2.5:7b)"
# Only boost a model with the exact ID
harbor config set boost.model_filter id=llama3.1:8b
```

This filter runs _after_ the boosted models (per module) are added, so you can filter them out as well.

**Modules configuration**

You can configure modules using either `harbor boost modules` alias or by editing the `HARBOR_BOOST_MODULES` variable in the `.env` file.

```bash
# Enable the module
harbor boost modules add <module>
# Disable the module
harbor boost modules rm <module>
# List enabled modules
harbor boost modules ls
```

Note that new Harbor releases might introduce new modules, so the default value of this setting could change in the future. Check out [Harbor Profiles](./3.-Harbor-CLI-Reference#harbor-profile) for a way to save and restore your configuration.

**Host Port**

You can adjust the port that `boost` will be linked to on the host. The default is `34131`.

```bash
# Set the port
harbor config set boost.host.port 8042
# Restart for changes to take effect
harbor restart boost
```

### Boost Modules & Configuration

`boost` is built from modules implementing specific optimisation workflows. Those aren't limited to the reasoning or prompt re-writing, but can include any transformation that can help the downstream model to perform better.

Modules can be enabled/disabled and configured via the Harbor CLI or the `.env` file manually. You'll need
to restart the `boost` service for the changes to take effect.

```bash
# Enable/Disable a module
harbor boost modules add <module>
harbor boost modules rm <module>
```

> [!TIP]
> You can use Harbor profiles to quickly rollback to the default configuration.
> ```bash
> # Save current changes, if needed
> harbor profile save <name>
> # Rollback to the default configuration
> harbor profile use default
> ```


#### `rcn` - recursive certainty validation

RCN is an original technique based on two principles: _context expansion_ and _self-validation_. It works by first expanding the context of the input by asking the model to explain the meaning of the every word in the prompt. Then, a completion is generated, then model is asked to validate how sure it is that the answer is correct. After two iterations, model is asked to give a final answer.

```bash
# Enable the module
harbor boost modules add rcn
```

**Parameters**

- `strat` - strategy for selection of the messages to rewrite. Default is `match`
  - `all` - match all messages
  - `first` - match first message regardless of the role
  - `last` - match last message regardless of the role
  - `any` - match one random message
  - `percentage` - match a percentage of random messages from the conversation
  - `user` - match all user messages
  - `match` - use a filter to match messages
- `strat_params` - parameters (filter) for the selection strategy. Default matches all user messages
  - `percentage` - for `percentage` strat - the percentage of messages to match, default is `50`
  - `index` - for `match` strat - the index of the message to match
  - `role` - for `match` strat - the role of the message to match
  - `substring` - for `match` strat - will match messages containing the substring

**Example**

```bash
# Configure message selection
# to match last user message
harbor boost rcn strat match
harbor boost rcn strat_params set role user
harbor boost rcn strat_params set index -1
```

#### `klmbr` - boost LLM creativity

> Handle: `klmbr`

![klmbr screenshot](https://github.com/av/klmbr/raw/main/assets/c4ndl3.png)

Boosts model creativity by applying character-level random rewrites to the input. Read a full overview of the technique in the [source repo](https://github.com/av/klmbr).

Every LLM will respond to rewrites in a different way. Some models will generate more diverse completions, while others might start generating completely random sequences. Default parameters are tuned for Llama 3.1 8B, you might want to adjust them when running with a different model.

**Parameters**

- `percentage` - amount of characters to rewrite in the input. Default is `35`
- `mods` - types of rewrites to apply. Default is `all`, available options:
  - `capitalize` - swaps character capitalization
  - `diacritic` - adds a random diacritic to the character
  - `leetspeak` - replaces characters with leetspeak equivalents
  - `remove_vowel` - removes vowels from the input
- `strat` - strategy for selection of the messages to rewrite. Default is `match`
  - `all` - match all messages
  - `first` - match first message regardless of the role
  - `last` - match last message regardless of the role
  - `any` - match one random message
  - `percentage` - match a percentage of random messages from the conversation
  - `user` - match all user messages
  - `match` - use a filter to match messages
- `strat_params` - parameters (filter) for the selection strategy. Default matches all user messages
  - `percentage` - for `percentage` strat - the percentage of messages to match, default is `50`
  - `index` - for `match` strat - the index of the message to match
  - `role` - for `match` strat - the role of the message to match
  - `substring` - for `match` strat - will match messages containing the substring

**Examples**

```bash
# Reduce the rewrite percentage
harbor boost klmbr percentage 20

# Enable/disable rewrite modules
harbor boost klmbr mods rm all
harbor boost klmbr mods add capitalize
harbor boost klmbr mods add diacritic
harbor boost klmbr mods add leetspeak
harbor boost klmbr mods add remove_vowel

# Change the selection strategy
# 1. Match all user messages
harbor boost klmbr strat match
harbor boost klmbr strat_params role user
# 2. Match the last message (regardless of the role)
harbor boost klmbr strat match
harbor boost klmbr strat_params index -1
# 3. Match messages containing a substring
harbor boost klmbr strat match
harbor boost klmbr strat_params substring "random"
```

#### `g1` - o1-like reasoning chains

Dynamic Chain-of-Thought pattern.

See [original implementation for Grok](https://github.com/bklieger-groq/g1). Harbor also has a [dedicated `ol1` service](./2.3.19-Satellite:-ol1) (UI only) that implements the same technique.

```bash
# Enable the module
harbor boost modules add g1
```

**Parameters**

- `max_steps` - Maximum amount of iterations for self-reflection, default is 15
- `strat` - strategy for selection of the messages to rewrite. Default is `match`
  - `all` - match all messages
  - `first` - match first message regardless of the role
  - `last` - match last message regardless of the role
  - `any` - match one random message
  - `percentage` - match a percentage of random messages from the conversation
  - `user` - match all user messages
  - `match` - use a filter to match messages
- `strat_params` - parameters (filter) for the selection strategy. Default matches all user messages
  - `percentage` - for `percentage` strat - the percentage of messages to match, default is `50`
  - `index` - for `match` strat - the index of the message to match
  - `role` - for `match` strat - the role of the message to match
  - `substring` - for `match` strat - will match messages containing the substring

#### `mcts` - Monte Carlo Tree Search

This is a less-cool version of the [Visual Tree Of Thoughts](https://openwebui.com/f/everlier/mcts) Open WebUI Function. Less cool because there's no way to rewrite the message content from a proxy side (yet), so all of the intermediate outputs are additive.

Nonetheless, the core of the technique is the same and is based on the Tree Of Thoughts and MCTS algorithms. An initial "idea" or answer is generated and then is improved upon for a given amount of steps.

```bash
# Enable the module
harbor boost modules add mcts
```

**Parameters**

All parameters below are prefixed with `boost.mcts.` in `harbor config`

- `strat` - strategy for selection of the messages to rewrite. Default is `match`, other values:
  - `all` - match all messages
  - `first` - match first message regardless of the role
  - `last` - match last message regardless of the role
  - `any` - match one random message
  - `percentage` - match a percentage of random messages from the conversation
  - `user` - match all user messages
  - `match` - use a filter to match messages
- `strat_params` - parameters (filter) for the selection strategy. Default matches all user messages, fields:
  - `percentage` - for `percentage` strat - the percentage of messages to match, default is `50`
  - `index` - for `match` strat - the index of the message to match
  - `role` - for `match` strat - the role of the message to match
  - `substring` - for `match` strat - will match messages containing the substring
- `max_iterations` - Maximum amount of Monte Carlo iterations to run (same tree), default is `2`
- `max_simulations` - Improvement steps per iteration, default is `2`
- `max_thoughts` - This number + 1 will be amount of improved variants to generate per node


```bash
# Strategy to find the message to start from
harbor config set boost.mcts.strat match
# Match last user message, for example
harbor config set boost.mcts.strat_params role=user,index=-1
```

#### `eli5` - Explain Like I'm 5

Based on a simple idea of explaining complex things in a simple way. The module will ask the LLM to explain a question to itself first and then will use that explanation for the final answer.

**Parameters**

`eli5` module supports selection strategy parameters identical to `mcts`, `g1`, and `rcn` modules, just under the `boost.eli5` prefix.

```bash
# Strategy to find the message to start from
harbor config set boost.eli5.strat match
# Match last user message, for example
harbor config set boost.eli5.strat_params role=user,index=-1
```

#### `supersummer` - Super Summarization

Based on a technique of generation of a summary of the given given content from key questions. The module will ask the LLM to provide a given amount of key questions and then will use them to guide the generation of the summary.

**Parameters**

`supersummer` module supports selection strategy parameters identical to `mcts`, `g1`, and `rcn` modules, just under the `boost.supersummer` prefix.

```bash
# Strategy to find the message to start from
harbor config set boost.supersummer.strat match
# Match last user message, for example
harbor config set boost.supersummer.strat_params role=user,index=-1
```

In addition to that, it's possible to adjust number of questions the model will generate, as well as the desired length of the summary.

```bash
# Number of questions to generate
harbor config set boost.supersummer.questions 3
# Length of the summary, you can use any
# textual specification, like "one paragraph"
harbor config set boost.supersummer.length "few paragraphs"
```

Here're sample questions and summary that `supersummer` generated from Harbor's readme:

<details>

<summary>Sample questions and summary</summary>

### Questions

**What is Harbor, and what are its primary functions?**
(This question addresses the central theme or argument of the text, which is to introduce Harbor as a containerized LLM toolkit.)

**What services can be managed with Harbor, and how does it facilitate their use?**
(This question highlights important facts or evidence, such as the various services listed in the "Services" section, and how Harbor enables easy management and usage of these services.)

**How does Harbor simplify local LLM development and experimentation?**
(This question reveals the author's purpose or perspective, which is to make local LLM development more convenient and streamlined by providing a unified CLI interface for managing services and configurations.)

**What benefits does Harbor provide over using individual Docker Compose files or Linux administration commands?**
(This question explores any significant implications or conclusions of using Harbor, such as the convenience factor and workflow centralisation it offers.)

**Can Harbor be used in conjunction with existing Docker setups, or is it intended to replace them entirely?**
(This question highlights important facts or evidence about Harbor's purpose and scope, such as its ability to co-exist with existing Docker setups and provide added value through its convenience features.)


### Summary

Harbor is a containerized Long-Short-Memory (LLM) toolkit that enables effortless management of LLM backends, APIs, frontends, and services. Developed as an open-source project, Harbor consists of a Command-Line Interface (CLI) and a companion application to help manage and run AI services in a unified manner.

Harbor offers several key features:

- **Managed Services**: The platform allows users to easily manage various LLM-related services, such as UIs (User Interfaces), Backends, Frontends, and Satellites.
- **Unified CLI Interface**: Harbor provides a single command-line interface for managing multiple services, eliminating the need for manual configuration and streamlining development workflows.
- **Convenience Utilities**: A range of convenience tools helps users manage LLM-related tasks efficiently, such as setting up services, debugging, creating URLs, and establishing network tunnels.
- **Cache Sharing and Reuse**: Harbor shares and reuses host caches, significantly enhancing model performance and reducing memory consumption across supported services (e.g., Hugging Face models, Ollama).
- **Config Profiles**: The application allows users to manage multiple configuration profiles for different development tasks or projects.

Harbor's purpose is not only to provide a convenient platform but also to simplify local LLM development by making it easier to setup and experiment with various LLM-related services. As such, Harbor can perfectly align with existing Docker setups and offers several benefits over manual Linux administration commands, like ease of use and streamlined configurations management.

As the author implies, the main benefit of using Harbor lies in its ability to simplify local LLM development and reduce time required for experiments and prototyping steps in a unified and convenient setup.

</details>


### API

`boost` works as an OpenAI-compatible API proxy. It'll query configured downstream services for which models they serve and provide "boosted" wrappers in its own API.

See the [http catalog](https://github.com/av/harbor/blob/main/http-catalog/boost.http) entry for some sample requests.

**Authorization**

When [configured](#boost-configuration) to require an API key, you can provide the API key in the `Authorization` header.

```http
<!-- All three versions are accepted -->
Authorization: sk-boost
Authorization: bearer sk-boost
Authorization: Bearer sk-boost
```

**`GET /v1/models`**

List boosted models. `boost` will serve additional models as per enabled modules. For example:

```jsonc
[
  {
    // Original, unmodified model proxy
    "id": "llama3.1:8b",
    // ...
  },
  {
    // LLM with klmbr technique applied
    "id": "klmbr-llama3.1:8b",
    // ...
  },
  {
    // LLM with rcn technique applied
    "id": "rcn-llama3.1:8b",
    // ...
  }
]
```

**`POST /v1/chat/completions`**

Chat completions endpoint.
  - Supports all parameters from the downstream API, for example `json` format for Ollama
  - Supports streaming completions

**`GET /events/:stream_id`**

Listen to a specific stream of events (associated with a single completion workflow). The stream ID is a unique identifier of the LLM instance processing the request (you may decide to advertise/pass it to the client in the workflow's code).

**`GET /health`**

Health check endpoint. Returns `{ status: 'ok' }` if the service is running.

### Custom Modules

It's possible to create custom modules for `boost`, using the built-in abstractions.
You can write a module in Python, put it in a folder and it'll be served by boost in the same
way as the built-in modules.

Here's a simplest example, a module that echoes the input back to the user:

```python
ID_PREFIX = "echo"
def apply(llm, chat):
  await llm.emit_message(prompt=chat.tail.content)
```

Read more on a dedicated [Custom Modules](./5.2.-Harbor-Boost-Custom-Modules) page.

### Standalone usage

You can run boost as a standalone Docker container. See [harbor-boost](https://github.com/av/harbor/pkgs/container/harbor-boost) package in GitHub Container Registry.

```bash
# [Optional] pre-pull the image
docker pull ghcr.io/av/harbor-boost:latest
```

**Configuration**

`boost` can be configured via environment variables, here's a reference of what's currently supported, with respective defaults.

```bash
# OpenAI-compatible APIs to boost. Semicolon-separated list
# Example: "http://localhost:11434/v1;http://localhost:8014/openai"
# ⚠️ Even if the API doesn't require a key, you still need to provide
# a placeholder in "BOOST_OPENAI_KEYS" for it
HARBOR_BOOST_OPENAI_URLS              ""

# Keys for the OpenAI-compatible APIs to boost. Semicolon-separated list,
# must be index-matched with the URLs.
# Example: "key1;key2"
# ⚠️ You need to provide placeholder keys even if the API doesn't require them
HARBOR_BOOST_OPENAI_KEYS              ""

# Boost modules to enable. Semicolon-separated list
# ℹ️ Boost can still run a workflow even if the module is disabled,
# it just won't be served via the /v1/models API (be invisible to the user)
# Example: "klmbr;rcn;g1"
HARBOR_BOOST_MODULES                  "klmbr;rcn;g1"

# Folders with boost modules to load.
# You can specify more than one, semicolon-separated list
# Built-in modules are in the "modules" of the container,
# you can turn them off by providing a custom folder only
# Example: "modules;/root/boost_modules"
HARBOR_BOOST_MODULE_FOLDERS           "modules;custom_modules"

# Base models to serve via the boost API
HARBOR_BOOST_BASE_MODELS              false

# Filter models that will be served by the boost API
# Runs after the boost own models are added, so you can filter them as well
# Examples: "id.contains=llama", "id.regex=.+q8_0$", "id=llama3.1:8b"
HARBOR_BOOST_MODEL_FILTER             ""

# API key for the boost service
# If set, the key must be provided in the Authorization header
# Example: "sk-boost"
HARBOR_BOOST_API_KEY                  ""
# Allows specifying multiple keys instead of a single one
# Example: "sk-user1;sk-user2;sk-user3"
HARBOR_BOOST_API_KEYS                 ""

# Enable intermediate output for the boost modules
# "Intermediate" means everything except the final result.
# For example, status messages or internal monologue
# Note that it doesn't mean "all output" from the module,
# as module source can still decide to not emit specific things at all
# or inverse - emit them even if this setting is off
HARBOR_BOOST_INTERMEDIATE_OUTPUT      true

# Module specific configs:
# Klmbr
HARBOR_BOOST_KLMBR_PERCENTAGE         35
HARBOR_BOOST_KLMBR_MODS               all
HARBOR_BOOST_KLMBR_STRAT              match
HARBOR_BOOST_KLMBR_STRAT_PARAMS       role=user

# RCN
HARBOR_BOOST_RCN_STRAT                match
HARBOR_BOOST_RCN_STRAT_PARAMS         role=user,index=-1

# G1
HARBOR_BOOST_G1_STRAT                 match
HARBOR_BOOST_G1_STRAT_PARAMS          role=user,index=-1
HARBOR_BOOST_G1_MAX_STEPS             15
```

See the main portion of the guide for detailed explanation of these variables. You can also find the most complete overview of the supported variables in the [source](https://github.com/av/harbor/blob/main/boost/src/config.py#L141).

**Example**

```bash
# Start the container
docker run \
  # 172.17.0.1 is the default IP of the host, when running on Linux
  # So, the example below is for local ollama
  -e "HARBOR_BOOST_OPENAI_URLS=http://172.17.0.1:11434/v1" \
  -e "HARBOR_BOOST_OPENAI_KEYS=sk-ollama" \
  # Configuration for the boost modules
  -e "HARBOR_BOOST_MODULES=klmbr;rcn;g1" \
  -e "HARBOR_BOOST_KLMBR_PERCENTAGE=60" \
  # [Optional] mount folder with custom modules
  -v /path/to/custom_modules/folder:/app/custom_modules \
  -p 8004:8000 \
  ghcr.io/av/harbor-boost:latest

# In the separate terminal (or detach the container)
curl http://localhost:8004/health
curl http://localhost:8004/v1/models
```