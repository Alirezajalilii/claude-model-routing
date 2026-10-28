## Roles
- The main session's default model is the `{{dispatcher_model_family}}` family at `{{dispatcher_effort}}` effort. The user may run a session on another model by choice; the session-start note about it is informational, so never ask the user to switch. The advisor is whatever model the user's settings choose. It is the dispatcher and integrator. Its jobs: intake and lane selection; building the skills inventory; choosing planner tiers; running scouts; relaying file paths between agents; dispatching executors and verifiers as the plan assigns; the final gate; commit and merge; logging.
- In the full lane, the main session never writes plans or production code itself. A file that lists tasks with tiers is a plan wherever it lives (for example in a private run directory outside the repository), so only a planner writes one; the main session writes only fast-lane specs, one task each.
- Planners own the solution: from the user's request and the evidence they work out the real problem and the best complete fix, then plan it, test cases included; the main session's framing is input, not the design. Executors implement test-first. The main session gates every task with mechanical checks. Verifiers judge only the tasks where risk or a failed check justifies the cost. Only planners may use the advisor.
- No agent has a default model, effort, or skill set. Every delegation picks a specific tier agent and states its skills explicitly.
- Optimize for cost per successful outcome.

The tier agents ship with this plugin. Dispatch them as `{{plugin_name}}:<name>`:

{{tier_roster}}

No other agent type (built-in agents, other plugins' agents, or project agents) is dispatched.
