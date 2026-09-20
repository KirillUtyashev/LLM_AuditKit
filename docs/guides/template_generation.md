# Generating Resume Templates

Template generation takes an existing `pandas.DataFrame` and produces a configurable
number of resume templates for each job-posting scenario. It uses shared inference for
EDSL execution and stores a resumable CSV checkpoint. It does not load a dataset path;
dataset loading remains a separate pipeline stage.

For the complete validation and persistence contract, see the
[template generation component documentation](../components/template_generation.md).

## Prepare Prompt Files

Keep materially different resume layouts in versioned UTF-8 text files. A user prompt
must include the job posting, configured count, and required placeholder list:

```text
Create {templates_per_scenario} distinct, equally qualified resume templates for this
job posting:

{job_posting}

The role is in {city}. Preserve these tokens literally in every template:
{required_placeholders}
```

An optional ordinary system prompt may use the same source fields and aliases:

```text
You create realistic resume templates for hiring audits in {city}.
```

Single braces identify prompt fields. Generated resume templates use double-brace
tokens such as `{{name}}` and `{{address}}`; these tokens are later filled by template
population. Template generation rejects outputs that omit a required token or invent
an unknown one.

## Configure the DataFrame Run

Applications that already have a DataFrame can construct the stage directly:

```python
from pathlib import Path

import pandas as pd

from llm_auditkit.inference import (
    EDSLAdapter,
    InferenceConfig,
    InferenceOrchestrator,
    ModelConfig,
)
from llm_auditkit.templates import (
    TemplateDatasetSchema,
    TemplateGenerationConfig,
    TemplateGenerator,
    TemplateStore,
)

dataset = pd.DataFrame(
    {
        "posting": ["Hire a careful research assistant."],
        "city_name": ["Toronto"],
    }
)

config = TemplateGenerationConfig(
    templates_per_scenario=4,
    dataset_schema=TemplateDatasetSchema(
        job_posting_column="posting",
        context_columns={"city": "city_name"},
    ),
    prompt_template=Path("prompts/resume_templates_v1.txt").read_text(
        encoding="utf-8"
    ),
    system_prompt_template=Path("prompts/resume_system_v1.txt").read_text(
        encoding="utf-8"
    ),
    required_placeholders=["name", "address"],
    inference=InferenceConfig(
        models=[
            ModelConfig(
                config_id="openai-template-v1",
                provider="openai",
                model="gpt-4o-2024-08-06",
                parameters={"temperature": 0},
            )
        ],
        batch_size=10,
    ),
    model_config_id="openai-template-v1",
    save_after_each_result=True,
)

generator = TemplateGenerator(
    InferenceOrchestrator(EDSLAdapter()),
    TemplateStore("results/resume_templates.csv"),
)
```

The schema maps semantic prompt fields to the caller's columns. Other columns are
preserved in output. A `scenario_id` column is optional: AuditKit creates stable IDs
internally when it is absent. Exact duplicate source rows need an ordinary stable
replicate column so they can be identified separately.

`batch_size=10` means at most ten pending scenarios are submitted in one logical
shared-inference batch. EDSL handles provider concurrency, rate limiting, caching, and
retries within that batch.

## Preview and Generate

Preview a small pending batch before spending tokens:

```python
preview = generator.preview(dataset, config, batch_number=1)
for rendered in preview.prompts:
    print(rendered.system_prompt)
    print(rendered.user_prompt)
```

Run with EDSL's blocking path:

```python
output = generator.generate(dataset, config)
```

Or use EDSL's native async path from an existing event loop:

```python
output = await generator.generate_async(dataset, config)
```

Both paths build and validate the same requests, return the same DataFrame shape, and
use the same checkpoint boundaries. They submit batches sequentially; template
generation does not add its own worker pool or retry loop.

## Understand Checkpoints and Output

The output preserves source columns and adds stable generation and request identity,
`template_1` through `template_N`, plus error type and message columns. With
`save_after_each_result=True`, each handled scenario is saved through atomic CSV
replacement before the next result is applied.

Rerunning against the same dataset, configuration, and output path skips valid
completed scenarios and retries failed scenarios. AuditKit fingerprints prompt text,
schema, template count, placeholders, and the selected model configuration, so a
content-affecting change cannot silently reuse an incompatible checkpoint. Batch size
and checkpoint frequency may change between resumptions because they do not define the
generated content.
