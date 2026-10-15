import { useEffect, useState } from "react";
import { SessionView } from "./components/SessionView";
import { StartForm } from "./components/StartForm";

/** The session named by the address (`#/session/<id>`), if any. */
function sessionFromHash({ hash }: { readonly hash: string }): string | undefined {
  const match = /^#\/session\/(.+)$/.exec(hash);
  return match?.[1] === undefined ? undefined : decodeURIComponent(match[1]);
}

/** The root of the UI: start a conversation, or follow one (the address keeps its place). */
export function App() {
  const [sessionId, setSessionId] = useState(() => sessionFromHash({ hash: window.location.hash }));

  useEffect(() => {
    const onChange = () => setSessionId(sessionFromHash({ hash: window.location.hash }));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);

  return (
    <main>
      <h1>pn-llm-verif</h1>
      {sessionId === undefined ? (
        <StartForm
          onStarted={({ sessionId: started }) => {
            window.location.hash = `#/session/${encodeURIComponent(started)}`;
          }}
        />
      ) : (
        <>
          <p>
            <a href="#/">New conversation</a>
          </p>
          <SessionView sessionId={sessionId} />
        </>
      )}
    </main>
  );
}
