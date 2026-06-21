/goal Start or keep the experiment loop running in the terminal and monitored for this research idea. Closely monitor each loop so that if there are any issues, you can fix them and restart if
required. Basically, you are responsible for the output of the loop and making sure it runs
correctly. The loop should be designed so that it is able to naturally pick up on previous loop's
outputs or worktrees without having to reimplement everything
Ideally we want to have the same research run complete as many experiments as possible within the
same run, but of course this may not always be possible if the thread has learned a wrong
assumption or the spec/prompt needs to change - but this is the kind of thing we also want to
prevent happening in the first place. Periodically, you should think about what the biggest blocker
has been to have the research experiment run complete experiments autonomously end to end with signal outputs, focusing on the facts and observed behavior. Use a subagent to plan out what the best solution to this single problem is that prioritises most minimal implementation and prefers not to add extra logic into the orchestrator code or add new contracts, and prefers to add instructions into prompts. Review that plan and then assign a subagent to implement it. Make any high conviction changes that you think are you are sure will improve the workflow and enables the goal that is established in AGENTS.md, or make the outputs more human readable or allows the loop to continue more autonomously. It is important that each iteration of the loop can naturally build on what was done in previous loops or start something new, without having to implement
everything from scratch. Each loop can also run backfills of parquet files if required to be
consumed later or even in future loops. Keep all the outputs and worktrees organised and delete
anything that failed with useless/missing output, make sure that even as the number of experiments
grow, the work that has been done can easily be read by, a human, but also easy for an agent to
quickly compare different experiments and decide which one is better. If you come up with any
ideas that to improve the agent-control-plane that will help move towards this goal, get a subagent to plan out the implementation, just like you would for main blockers that you have faced.
