"""Local rendering for caller-owned text in EDSL 1.0.8 and 1.0.9.

Preview and async interviews use the agent's invigilator. The blocking Runner
reconstructs agents, surveys and questions from serialized data and renders
before cache lookup. Both paths install the same per-request prompt plan.
"""

from copy import copy

from edsl import Agent, Jobs
from edsl.invigilators import PromptConstructor
from edsl.invigilators.prompt_helpers import PromptPlan
from edsl.runner.render import RenderService
from edsl.runner.runner import Runner

from .exceptions import InferenceBatchError


class _LiteralPromptPlan:
    def __init__(self, body: str, persona: str | None, native_plan):
        self.native_plan = native_plan if native_plan is not None else PromptPlan()
        self.body = body
        self.persona = persona

    def get_prompts(self, **components):
        # Only the native answering instructions remain in this component.
        components["question_instructions"] = self.body + components["question_instructions"]
        if self.persona is not None:
            # Match the adapter's normal Jinja dictionary presentation, with
            # caller data inserted after all template evaluation.
            components["agent_persona"] = "Your traits: " + str({"persona": self.persona})
        return self.native_plan.get_prompts(**components)


def _render_inputs(question, scenario, literal_agent, native_plan):
    # EDSL separately re-renders the question when validating responses. Its
    # metadata contains only the body length. A render-only copy presents an
    # empty body and lets EDSL generate the standard free-text or dict suffix.
    suffix_question = copy(question)
    suffix_question.question_presentation = "{{ '' }}"
    plan = _LiteralPromptPlan(
        scenario[literal_agent.prompt_field], literal_agent.literal_persona, native_plan
    )
    return {"question": suffix_question, "prompt_plan": plan}


class LiteralAgent(Agent):
    """Install the literal plan on preview and asynchronous invigilators."""

    def __init__(self, *, prompt_field, literal_persona, **kwargs):
        super().__init__(**kwargs)
        self.prompt_field = prompt_field
        self.literal_persona = literal_persona

    def create_invigilator(self, *, scenario, question, prompt_plan=None, **kwargs):
        kwargs.update(_render_inputs(question, scenario, self, prompt_plan))
        return super().create_invigilator(scenario=scenario, **kwargs)


class _LiteralRenderService(RenderService):
    def __init__(self, storage, literal_agent, native_plan):
        super().__init__(storage)
        self.literal_agent = literal_agent
        self.native_plan = native_plan

    def _render_with_objects(self, *, scenario, agent, question, **context):
        prompts = PromptConstructor(
            scenario=scenario, agent=agent, **context,
            **_render_inputs(question, scenario, self.literal_agent, self.native_plan),
        ).get_prompts()
        return {
            "user_prompt": prompts["user_prompt"].text,
            "system_prompt": prompts["system_prompt"].text,
            "files_list": prompts.get("files_list"),
        }

    def _render_with_edsl(self, **kwargs):
        raise InferenceBatchError("Unsupported EDSL literal prompt rendering path")


class LiteralJobs(Jobs):
    """Use the native local runner with a renderer scoped to this job."""

    def _execute_with_runner(self):
        parameters = self.run_config.parameters
        # EDSL introduced its max_concurrency runner option in 1.0.9.
        if hasattr(parameters, "max_concurrency"):
            runner = Runner(max_workers=parameters.max_concurrency or 400)
        else:
            runner = Runner()
        runner._render_worker._render_service = _LiteralRenderService(
            runner._storage, self.agents[0], getattr(self.models[0], "prompt_plan", None)
        )
        handle = runner.submit(
            self,
            n=parameters.n,
            cache=self.run_config.environment.cache,
            stop_on_exception=parameters.stop_on_exception,
            stream_to_cas=True,
        )
        return handle.results(show_progress=parameters.progress_bar)

    def _start_remote_inference_job(self, job_handler=None):
        raise InferenceBatchError(
            "EDSL whole-job offload cannot preserve literal prompt text. "
            "Configure EDSL to render the job locally before calling the selected provider."
        )
