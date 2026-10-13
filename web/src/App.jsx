import { useCallback, useEffect, useState } from "react";
import { configurationError, supabase as defaultClient } from "./lib/supabase";
import { SignIn } from "./components/SignIn";
import { Dashboard } from "./components/Dashboard";
import { UploadMemo } from "./components/UploadMemo";
import { ConversionProgress } from "./components/ConversionProgress";
import { BrandCrest, BrandLockup } from "./components/BrandIdentity";
import { ExpiredInvitation, InviteOnboarding } from "./components/InviteOnboarding";
import { inviteRouteState, normalSignInUrl } from "./lib/inviteOnboarding";
import { SupportIncident } from "./components/SupportIncident";

export function App({ client = defaultClient }) {
  const [auth, setAuth] = useState({ loading: true, session: null });
  const [screen, setScreen] = useState({ name: "dashboard", job: null });
  const [inviteRoute, setInviteRoute] = useState(() => inviteRouteState());
  const [setupComplete, setSetupComplete] = useState(false);
  const updateCurrentJob = useCallback((job) => {
    setScreen((current) => current.name === "progress" ? { ...current, job } : current);
  }, []);

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
  const returnToSignIn = () => {
    window.history.replaceState({}, "", normalSignInUrl());
    setInviteRoute({ active: false, expired: false, errorCode: null });
  };
  const finishOnboarding = () => {
    setAuth({ loading: false, session: null });
    setSetupComplete(true);
    returnToSignIn();
  };
  if (inviteRoute.expired) return <ExpiredInvitation onSignIn={returnToSignIn} />;
  if (auth.loading) {
    return <main className="center-message"><p>Opening your teacher workspace…</p></main>;
  }
  if (inviteRoute.active && !auth.session) return <ExpiredInvitation onSignIn={returnToSignIn} />;
  if (inviteRoute.active) return <InviteOnboarding client={client} session={auth.session} onComplete={finishOnboarding} />;
  if (!auth.session) return <SignIn client={client} setupComplete={setupComplete} />;

  const user = auth.session.user;
  const dashboard = () => setScreen({ name: "dashboard", job: null });

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand-button" onClick={dashboard}>
          <BrandCrest decorative />
          <BrandLockup compact />
        </button>
        <div className="account">
          <SupportIncident client={client} user={user} context={{ job: screen.job, currentView: screen.name }} />
          <span className="account-identity"><small>Teacher workspace</small>{user.email}</span>
          <button className="button quiet" onClick={() => client.auth.signOut()}>Sign out</button>
        </div>
      </header>

      {screen.name === "dashboard" && (
        <Dashboard
          client={client}
          user={user}
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
          onRevise={() => setScreen({ name: "upload", job: null })}
          onJobChange={updateCurrentJob}
        />
      )}
    </div>
  );
}
