<!-- Chunk note (Planner, Investigator, Reporter in the Markovian loop). Does: explains the `chunk`
state in the input. Must not: override the task, plan or output format. -->
The input also has `chunk`: the investigation state built for this step. It starts with the goal,
then "State so far" (the current ranking of explanations, what has been ruled out and why, open
questions and the rounds left) and "Evidence" (World Model items selected for this step, each with
why it was selected). Use it to avoid repeating work and to stay consistent with what is already
measured. It is context only: the task, plan and output format above still decide what you return.
