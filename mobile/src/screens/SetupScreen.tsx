import React, { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
} from "react-native";

import { probeServer } from "../api/spoolman";
import { ForwardAuthError } from "../lib/forwardAuth";
import { normalizeBaseUrl, type ServerProfile } from "../lib/serverProfile";

interface SetupScreenProps {
  onDone: (profile: ServerProfile, token: string | null) => void;
}

interface PortalState {
  baseUrl: string;
  token: string | null;
  authUrl: string | null;
}

export function SetupScreen({ onDone }: SetupScreenProps) {
  const [url, setUrl] = useState("");
  const [tokenInput, setTokenInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [portal, setPortal] = useState<PortalState | null>(null);

  const connect = async () => {
    const baseUrl = normalizeBaseUrl(url);
    if (!baseUrl) {
      setError("Enter your server address, e.g. http://pi:7912 or 192.168.1.10:7912");
      return;
    }
    setBusy(true);
    setError(null);
    setPortal(null);
    try {
      const { info, auth } = await probeServer(baseUrl);
      const token = tokenInput.trim() || null;
      const profile: ServerProfile = { baseUrl, name: `Spoolman ${info.version}` };
      if (auth?.auth_required && !token) {
        Alert.alert(
          "Server requires authentication",
          auth.accounts_enabled
            ? "You can log in with your username and password inside the app once connected."
            : "This server uses an API token (SPOOLMAN_API_TOKEN). Paste it below, or continue and enter it when prompted.",
          [
            { text: "Back", style: "cancel" },
            { text: "Continue", onPress: () => onDone(profile, null) },
          ],
        );
        return;
      }
      onDone(profile, token);
    } catch (e) {
      if (e instanceof ForwardAuthError) {
        // Server is behind a login portal (Authelia, etc.). We cannot probe
        // past it, so offer to open the app and sign in there — the session
        // cookie set during that login is shared with native requests.
        setPortal({ baseUrl, token: tokenInput.trim() || null, authUrl: e.authUrl });
        return;
      }
      setError(
        `Could not reach a Spoolman server at ${baseUrl} — check the address, port and that ` +
          `your phone is on the same network. (${e instanceof Error ? e.message : String(e)})`,
      );
    } finally {
      setBusy(false);
    }
  };

  const continueToPortal = () => {
    if (!portal) {
      return;
    }
    onDone({ baseUrl: portal.baseUrl, name: "Spoolman" }, portal.token);
  };

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <Text style={styles.title}>Spoolman Companion</Text>
        <Text style={styles.subtitle}>
          Connect to your self-hosted Spoolman server. Plain http:// on your LAN works — no TLS
          setup needed.
        </Text>

        <Text style={styles.label}>Server address</Text>
        <TextInput
          style={styles.input}
          value={url}
          onChangeText={setUrl}
          placeholder="http://pi:7912"
          placeholderTextColor="#888888"
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          editable={!busy}
          onSubmitEditing={connect}
        />

        <Text style={styles.label}>API token (optional)</Text>
        <TextInput
          style={styles.input}
          value={tokenInput}
          onChangeText={setTokenInput}
          placeholder="Only if the server sets SPOOLMAN_API_TOKEN"
          placeholderTextColor="#888888"
          autoCapitalize="none"
          autoCorrect={false}
          editable={!busy}
        />

        {error && <Text style={styles.error}>{error}</Text>}

        {portal && (
          <Text style={styles.notice}>
            This server is behind a login portal
            {portal.authUrl ? ` (${originLabel(portal.authUrl)})` : ""} — an extra sign-in that
            sits in front of Spoolman. Continue to sign in inside the app; scanning works once
            you're through.
          </Text>
        )}

        {portal ? (
          <>
            <TouchableOpacity
              style={styles.button}
              onPress={continueToPortal}
              accessibilityRole="button"
            >
              <Text style={styles.buttonText}>Continue to sign in</Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.secondaryButton}
              onPress={() => setPortal(null)}
              accessibilityRole="button"
            >
              <Text style={styles.secondaryButtonText}>Back</Text>
            </TouchableOpacity>
          </>
        ) : (
          <TouchableOpacity
            style={[styles.button, busy && styles.buttonDisabled]}
            onPress={connect}
            disabled={busy}
            accessibilityRole="button"
          >
            {busy ? (
              <ActivityIndicator color="#ffffff" />
            ) : (
              <Text style={styles.buttonText}>Connect</Text>
            )}
          </TouchableOpacity>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

/** "https://auth.example.ch/?rd=…" -> "auth.example.ch" for a compact label. */
function originLabel(authUrl: string): string {
  const match = authUrl.match(/^https?:\/\/([^/?#]+)/i);
  return match ? match[1] : authUrl;
}

const styles = StyleSheet.create({
  flex: {
    flex: 1,
    backgroundColor: "#ffffff",
  },
  container: {
    flexGrow: 1,
    justifyContent: "center",
    padding: 28,
    backgroundColor: "#ffffff",
  },
  title: {
    fontSize: 26,
    fontWeight: "800",
    color: "#dc7734",
  },
  subtitle: {
    marginTop: 8,
    marginBottom: 28,
    fontSize: 14,
    lineHeight: 20,
    color: "#666666",
  },
  label: {
    fontSize: 13,
    fontWeight: "600",
    color: "#555555",
    marginBottom: 6,
  },
  input: {
    borderWidth: 1,
    borderColor: "#cccccc",
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    color: "#111111",
    backgroundColor: "#ffffff",
    marginBottom: 18,
  },
  error: {
    color: "#d4380d",
    marginBottom: 16,
    fontSize: 13,
    lineHeight: 18,
  },
  notice: {
    color: "#555555",
    marginBottom: 16,
    fontSize: 13,
    lineHeight: 19,
  },
  button: {
    backgroundColor: "#dc7734",
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: "center",
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "700",
  },
  secondaryButton: {
    marginTop: 12,
    paddingVertical: 12,
    alignItems: "center",
  },
  secondaryButtonText: {
    color: "#888888",
    fontSize: 15,
    fontWeight: "600",
  },
});
