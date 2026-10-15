import { type FormEvent, useState } from "react";

/** A text box that sends what the user writes; disabled while it is not the user's turn. */
export function Composer({
  label,
  disabled,
  onSend,
}: {
  readonly label: string;
  readonly disabled: boolean;
  readonly onSend: (args: { readonly text: string }) => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | undefined>(undefined);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = text.trim();
    if (trimmed === "") {
      return;
    }
    try {
      await onSend({ text: trimmed });
      setText("");
      setError(undefined);
    } catch (failure: unknown) {
      setError(failure instanceof Error ? failure.message : String(failure));
    }
  }

  return (
    <form onSubmit={submit} className="composer">
      <label>
        {label}
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          disabled={disabled}
        />
      </label>
      <button type="submit" disabled={disabled || text.trim() === ""}>
        Send
      </button>
      {error !== undefined && <p role="alert">{error}</p>}
    </form>
  );
}
