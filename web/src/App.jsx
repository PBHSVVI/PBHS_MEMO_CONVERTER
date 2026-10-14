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
import { MandatoryPasswordChange } from "./components/MandatoryPasswordChange";
import { FIRST_LOGIN, firstLoginStatus } from "./lib/firstLogin";

export function App({ client = defaultClient }) {
  const [auth, setAuth] = useState({ loading: true, session: null });
  const [screen, setScreen] = useState({ name: "dashboard", job: null });
  const [inviteRoute, setInviteRoute] = useState(() => inviteRouteState());
  const [setupComplete, setSetupComplete] = useState(false);
  const [firstLogin, setFirstLogin] = useState({ loading: false, status: null });
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

  useEffect(() => {
    if (!client || !auth.session?.user?.id || inviteRoute.active) {
      setFirstLogin({ loading: false, status: null });
      return undefined;
    }
    let mounted = true;
    setFirstLogin({ loading: true, status: null });
    firstLoginStatus(client).then(({ status }) => {
      if (mounted) setFirstLogin({ loading: false, status });
    });
    return () => { mounted = false; };
  }, [client, auth.session?.user?.id, inviteRoute.active]);

  if (!client) {
    return <main className="center-message"><section className="notice danger">{configurationError}</section></main>;
  }
  const returnToSignIn = () => {
    window.history.replaceState({}, "", normalSignInUrl());
    setInviteRoute({ active: false, expired: false, errorCode: null });
  };
  const openCodeSetup = () => {
    const url = new URL(window.location.href);
    url.search = "?onboarding=setup";
    url.hash = "";
    window.history.replaceState({}, "", url);
    setInviteRoute({ active: true, expired: false, errorCode: null });
  };
  const finishOnboarding = () => {
    setAuth({ loading: false, session: null });
    setSetupComplete("otp");
    returnToSignIn();
  };
  if (inviteRoute.expired) return <ExpiredInvitation onSetup={openCodeSetup} />;
  if (auth.loading) {
    return <main className="center-message"><p>Opening your teacher workspace…</p></main>;
  }
  if (inviteRoute.active) return <InviteOnboarding client={client} onComplete={finishOnboarding} />;
  if (!auth.session) return <SignIn client={client} setupComplete={setupComplete} />;

  if (firstLogin.loading || !firstLogin.status) {
    return <main className="center-message"><p>Checking your teacher account…</p></main>;
  }
  if (firstLogin.status === FIRST_LOGIN.PASSWORD_CHANGE_REQUIRED) {
    return <MandatoryPasswordChange
      client={client}
      email={auth.session.user.email}
      onComplete={() => {
        setAuth({ loading: false, session: null });
        setSetupComplete("password");
        setFirstLogin({ loading: false, status: null });
      }}
    />;
  }
  if (firstLogin.status !== FIRST_LOGIN.READY) {
    return (
      <main className="center-message">
        <section className="notice danger">
          <p>Your PBHS Mathematics account is not available. Please contact the Mathematics Department administrator.</p>
          <button className="button secondary" onClick={() => client.auth.signOut()}>Sign out</button>
        </section>
      </main>
    );
  }

  const user = auth.session.user;
  const dashboard = () => setScreen({ name: "dashboard", job: null });
  const retainCurrentJob = (job) => setScreen((current) => ({ ...current, job }));

  return (
    <div className="app">
      <header className="topbar">
        <button className="brand-button" onClick={dashboard}>
          <BrandCrest decorative />
          <BrandLockup compact />
        </button>
        <div className="account">
          <button className="button home-action" onClick={dashboard}>Home</button>
          <SupportIncident client={client} user={user} context={{ job: screen.job, currentView: screen.name }} />
          <span className="account-identity"><small>Teacher workspace</small>{user.email}</span>
          <button className="button quiet" onClick={() => client.auth.signOut()}>Sign out</button>
        </div>
      </header>

      {screen.name === "dashboard" && (
        <Dashboard
          client={client}
          user={user}
          onConvert={(context) => setScreen({ name: "upload", job: null, uploadContext: context })}
          onOpen={(job) => setScreen({ name: "progress", job })}
        />
      )}
      {screen.name === "upload" && (
        <UploadMemo
          client={client}
          user={user}
          onBack={dashboard}
          initialContext={screen.uploadContext}
          onJobCreated={retainCurrentJob}
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
