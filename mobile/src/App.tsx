import { StatusBar } from "expo-status-bar";
import React, { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Platform, SafeAreaView, StatusBar as RNStatusBar, StyleSheet, View } from "react-native";

import type { ServerProfile } from "./lib/serverProfile";
import { MainScreen } from "./screens/MainScreen";
import { SetupScreen } from "./screens/SetupScreen";
import { clearProfile, loadProfile, loadToken, saveProfile, saveToken } from "./storage";

interface AppState {
  loading: boolean;
  profile: ServerProfile | null;
  token: string | null;
}

export default function App() {
  const [state, setState] = useState<AppState>({ loading: true, profile: null, token: null });

  useEffect(() => {
    (async () => {
      const [profile, token] = await Promise.all([loadProfile(), loadToken()]);
      setState({ loading: false, profile, token });
    })();
  }, []);

  const handleSetupDone = useCallback((profile: ServerProfile, token: string | null) => {
    setState({ loading: false, profile, token });
    saveProfile(profile).catch(() => {});
    saveToken(token).catch(() => {});
  }, []);

  const handleTokenChange = useCallback((token: string | null) => {
    setState((prev) => ({ ...prev, token }));
    saveToken(token).catch(() => {});
  }, []);

  const handleChangeServer = useCallback(() => {
    setState({ loading: false, profile: null, token: null });
    clearProfile().catch(() => {});
  }, []);

  return (
    <SafeAreaView style={styles.safeArea}>
      {state.loading ? (
        <View style={styles.loading}>
          <ActivityIndicator size="large" color="#dc7734" />
        </View>
      ) : state.profile ? (
        <MainScreen
          profile={state.profile}
          token={state.token}
          onTokenChange={handleTokenChange}
          onChangeServer={handleChangeServer}
        />
      ) : (
        <SetupScreen onDone={handleSetupDone} />
      )}
      <StatusBar style="auto" />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: "#ffffff",
    paddingTop: Platform.OS === "android" ? (RNStatusBar.currentHeight ?? 0) : 0,
  },
  loading: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
});
