import type { Plan } from "../model/types";
import { CodeBlock } from "./CodeBlock";
import { NoteBanner } from "./NoteBanner";

export function PlanView({ plan }: { plan: Plan }) {
  const artifactById = new Map(plan.artifacts.map((a) => [a.id, a]));

  return (
    <section className="plan" aria-live="polite">
      {plan.warnings.map((note) => (
        <NoteBanner key={note.id} note={note} />
      ))}

      <ol className="steps">
        {plan.steps.map((step) => (
          <li key={step.id} className="step">
            <h3>{step.title}</h3>
            {step.body && <p className="step-body">{step.body}</p>}
            {step.commands && <CodeBlock language="bash" content={step.commands.join("\n")} />}
            {step.code && <CodeBlock language={step.code.language} content={step.code.content} />}
            {(step.artifactIds ?? []).map((id) => {
              const artifact = artifactById.get(id);
              return artifact ? (
                <CodeBlock
                  key={id}
                  language={artifact.language}
                  title={artifact.title}
                  filename={artifact.filename}
                  content={artifact.content}
                />
              ) : null;
            })}
            {(step.notes ?? []).map((note) => (
              <NoteBanner key={note.id} note={note} />
            ))}
          </li>
        ))}
      </ol>
    </section>
  );
}
