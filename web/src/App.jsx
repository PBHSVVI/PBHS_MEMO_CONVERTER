import { useEffect, useState } from "react";
import { configurationError, supabase as defaultClient } from "./lib/supabase";
import { SignIn } from "./components/SignIn";
import { Dashboard } from "./components/Dashboard";
import { UploadMemo } from "./components/UploadMemo";
import { ConversionProgress } from "./components/ConversionProgress";

export function App({ client = defaultClient }) {
  const [auth, setAuth] = useState({ loading: true, session: null });
  const [screen, setScreen] = useState({ name: "dashboard", job: null });

  useEffect(() => {
    if (!client) {
      setAuth({ loading: false, session: null });
      return undefined;
    }
    let mounted = true;
    client.auth.getSession().then(({ data }) => {
      if (mounted) setAuth({ loading: false, session: data.session || null });
    });
    const { data } = client.auth.onAuthStateChange((_event, session) => {
      if (mounted) {
        setAuth({ loading: false, session: session || null });
        if (!session) setScreen({ name: "dashboard", job: null });
      }
    });
    return () => {
      mounted = false;
      data.subscription.unsubscribe();
    };
  }, [client]);

  if (!client) {
    return <main className="center-message"><section className="notice danger">{configurationError}</section></main>;
  }
  if (auth.loading) {
    return <main className="center-message"><p>Opening your teacher workspace…</p></main>;
  }
  if (!auth.session) return <SignIn client={client} />;

  const user = auth.session.user;
  const dashboard = () => setScreen({ name: "dashboard", job: null });

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand-button" onClick={dashboard}>
          <span className="brand-small" aria-hidden="true">∑</span>
          <span><strong>PBHS Mathematics</strong><small>Memo Converter</small></span>
        </button>
        <div className="account">
          <span>{user.email}</span>
          <button className="button quiet" onClick={() => client.auth.signOut()}>Sign out</button>
        </div>
      </header>

      {screen.name === "dashboard" && (
        <Dashboard
          client={client}
          onConvert={() => setScreen({ name: "upload", job: null })}
          onOpen={(job) => setScreen({ name: "progress", job })}
        />
      )}
      {screen.name === "upload" && (
        <UploadMemo
          client={client}
          user={user}
          onBack={dashboard}
          onCreated={(job) => setScreen({ name: "progress", job })}
        />
      )}
      {screen.name === "progress" && (
        <ConversionProgress
          client={client}
          user={user}
          initialJob={screen.job}
          onBack={dashboard}
        />
      )}
    </div>
  );
}
