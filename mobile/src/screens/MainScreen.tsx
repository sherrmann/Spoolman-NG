import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  BackHandler,
  Linking,
  Platform,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { WebView } from "react-native-webview";

import { ApiError, nfcLookup } from "../api/spoolman";
import { Fab } from "../components/Fab";
import { NfcModal } from "../components/NfcModal";
import { ScannerModal } from "../components/ScannerModal";
import { SettingsMenuModal } from "../components/SettingsMenuModal";
import { bytesToBase64 } from "../lib/base64";
import { buildNavigateScript, buildStartupInjection, parseWebViewMessage } from "../lib/inject";
import { decideScanAction, parseNdefCandidate } from "../lib/scanActions";
import { buildSettingsMenuEntries, type SettingsMenuAction } from "../lib/settingsMenu";
import { appUrl, originOf, shouldOpenExternally, type ServerProfile } from "../lib/serverProfile";
import {
  cancelNfcRead,
  ensureNfcStarted,
  isNfcEnabled,
  openNfcSettings,
  readSpoolmanTag,
  type TagReadResult,
} from "../nfc/readTag";
import { checkForUpdate, downloadAndInstallApk } from "../update/updater";
import { PasskeySetupModal } from "./PasskeySetupModal";

interface MainScreenProps {
  profile: ServerProfile;
  token: string | null;
  onTokenChange: (token: string | null) => void;
  onChangeServer: () => void;
}

export function MainScreen({ profile, token, onTokenChange, onChangeServer }: MainScreenProps) {
  const webviewRef = useRef<WebView>(null);
  const canGoBackRef = useRef(false);
  // The most recent off-origin https origin the WebView visited — usually the
  // forward-auth portal during the login round-trip, but any off-origin hop
  // (OAuth upstream, redirect) can land here too. Only a passkey-setup prefill
  // fallback for portals discovered after setup; the vetted setup-time
  // detection (profile.authOrigin) wins when present.
  const portalOriginRef = useRef<string | null>(null);
  const [scannerOpen, setScannerOpen] = useState(false);
  const [nfcStatus, setNfcStatus] = useState<string | null>(null);
  const [nfcAvailable, setNfcAvailable] = useState(false);
  const [updateStatus, setUpdateStatus] = useState<string | null>(null);
  const [passkeySetupOpen, setPasskeySetupOpen] = useState(false);

  const origin = originOf(profile.baseUrl);

  useEffect(() => {
    ensureNfcStarted().then(setNfcAvailable);
  }, []);

  const startInstall = useCallback(async (apkUrl: string) => {
    setUpdateStatus("Downloading update… 0%");
    try {
      await downloadAndInstallApk(apkUrl, (fraction) => {
        setUpdateStatus(`Downloading update… ${Math.round(fraction * 100)}%`);
      });
      // The system installer takes over here; clear our overlay.
      setUpdateStatus(null);
    } catch (e) {
      setUpdateStatus(null);
      Alert.alert("Update failed", errorMessage(e));
    }
  }, []);

  const runUpdateCheck = useCallback(
    async (manual: boolean) => {
      const info = await checkForUpdate();
      if (!info) {
        if (manual) {
          Alert.alert("You're up to date", "No newer companion app has been released.");
        }
        return;
      }
      Alert.alert(
        "Update available",
        `Version ${info.release.version} is available (you have ${info.currentVersion}).`,
        [
          { text: "Later", style: "cancel" },
          { text: "Release notes", onPress: () => Linking.openURL(info.release.htmlUrl).catch(() => {}) },
          {
            text: "Update",
            onPress: () => {
              if (info.release.apkUrl) {
                startInstall(info.release.apkUrl);
              }
            },
          },
        ],
      );
    },
    [startInstall],
  );

  // Quietly check for a newer release once per app launch (release builds only).
  useEffect(() => {
    if (!__DEV__) {
      runUpdateCheck(false).catch(() => {});
    }
  }, [runUpdateCheck]);

  // Android hardware back navigates the web app's history first.
  useEffect(() => {
    const sub = BackHandler.addEventListener("hardwareBackPress", () => {
      if (canGoBackRef.current) {
        webviewRef.current?.goBack();
        return true;
      }
      return false;
    });
    return () => sub.remove();
  }, []);

  const navigateTo = useCallback(
    (path: string) => {
      webviewRef.current?.injectJavaScript(buildNavigateScript(appUrl(profile.baseUrl, path)));
    },
    [profile.baseUrl],
  );

  const handleScanned = useCallback(
    (data: string) => {
      setScannerOpen(false);
      const action = decideScanAction(data);
      switch (action.kind) {
        case "navigate":
          navigateTo(action.target.path);
          break;
        case "clear":
          Alert.alert(
            "Clear-spool code",
            "This code tells external integrations (e.g. a printer) to clear their active spool — there is nothing to open in the app.",
          );
          break;
        case "retail":
          Alert.alert(
            "Retail barcode",
            `Scanned article number ${action.code}. Retail-barcode lookup comes in the next milestone — for now, search for it in the web UI.`,
          );
          break;
        default:
          Alert.alert("Not a Spoolman code", truncate(action.raw, 120));
      }
    },
    [navigateTo],
  );

  const lookupTag = useCallback(
    async (result: TagReadResult) => {
      // 1. NDEF URI/text payloads resolve locally — no server round-trip.
      for (const candidate of result.textCandidates) {
        const target = parseNdefCandidate(candidate);
        if (target) {
          navigateTo(target.path);
          return;
        }
      }

      // 2. Otherwise let the server decode it, like a Klipper NFC daemon:
      //    prefer a TigerTag NDEF payload, else the raw NTAG dump.
      const payload = result.tigertagPayload ?? result.rawDump;
      if (!payload) {
        Alert.alert(
          "Unrecognized tag",
          "No Spoolman data found on this tag. TigerTag (NTAG213) and NDEF tags are supported in this version.",
        );
        return;
      }
      const body = {
        raw_data_b64: bytesToBase64(payload),
        nfc_tag_uid: result.uidHex ?? undefined,
      };
      setNfcStatus("Asking the server about this tag…");
      try {
        const lookup = await nfcLookup(profile.baseUrl, token, body);
        setNfcStatus(null);
        if (lookup.success && lookup.spool_id) {
          navigateTo(`/spool/show/${lookup.spool_id}`);
          return;
        }
        if (lookup.success) {
          Alert.alert(
            "No spool bound to this tag",
            `The tag decoded as ${lookup.tag_format ?? "unknown"} but no spool matches. Create one from the tag data?`,
            [
              { text: "Cancel", style: "cancel" },
              {
                text: "Create spool",
                onPress: async () => {
                  try {
                    const created = await nfcLookup(profile.baseUrl, token, {
                      ...body,
                      auto_create: true,
                    });
                    if (created.success && created.spool_id) {
                      navigateTo(`/spool/show/${created.spool_id}`);
                    } else {
                      Alert.alert("Could not create spool", created.message || "Unknown error.");
                    }
                  } catch (e) {
                    Alert.alert("Could not create spool", errorMessage(e));
                  }
                },
              },
            ],
          );
          return;
        }
        Alert.alert("Tag not recognized", lookup.message || "The server could not decode this tag.");
      } catch (e) {
        setNfcStatus(null);
        Alert.alert("Tag lookup failed", errorMessage(e));
      }
    },
    [navigateTo, profile.baseUrl, token],
  );

  const handleNfcPress = useCallback(async () => {
    if (!nfcAvailable) {
      Alert.alert("NFC unavailable", "This device does not support NFC.");
      return;
    }
    if (!(await isNfcEnabled())) {
      Alert.alert("NFC is turned off", "Enable NFC in the system settings to scan spool tags.", [
        { text: "Cancel", style: "cancel" },
        { text: "Open settings", onPress: () => openNfcSettings() },
      ]);
      return;
    }
    setNfcStatus("Hold a spool tag against the back of your phone");
    try {
      const result = await readSpoolmanTag();
      setNfcStatus(null);
      await lookupTag(result);
    } catch {
      // Cancelled or session lost — the modal is already gone, stay quiet.
      setNfcStatus(null);
    }
  }, [lookupTag, nfcAvailable]);

  // Real menu instead of Alert.alert (#221): RN's Android Alert renders at most three
  // buttons and silently dropped "Passkey setup" and "Change server" from the old list.
  const [settingsOpen, setSettingsOpen] = useState(false);
  const handleSettings = useCallback(() => setSettingsOpen(true), []);
  const onSettingsSelect = useCallback(
    (action: SettingsMenuAction) => {
      setSettingsOpen(false);
      if (action === "reload") {
        webviewRef.current?.reload();
      } else if (action === "update-check") {
        runUpdateCheck(true);
      } else if (action === "passkey-setup") {
        setPasskeySetupOpen(true);
      } else if (action === "change-server") {
        onChangeServer();
      }
    },
    [onChangeServer, runUpdateCheck],
  );

  return (
    <View style={styles.container}>
      <WebView
        ref={webviewRef}
        source={{ uri: profile.baseUrl }}
        style={styles.webview}
        originWhitelist={["*"]}
        domStorageEnabled
        javaScriptEnabled
        // Share the WebView cookie jar with native fetch so a forward-auth
        // (Authelia, etc.) session cookie set during in-app login also
        // authenticates the native probe and NFC-lookup requests.
        sharedCookiesEnabled
        thirdPartyCookiesEnabled
        allowsBackForwardNavigationGestures
        injectedJavaScriptBeforeContentLoaded={buildStartupInjection(token, origin)}
        onMessage={(event) => {
          const message = parseWebViewMessage(event.nativeEvent.data, event.nativeEvent.url, origin);
          if (message && message.token !== token) {
            onTokenChange(message.token);
          }
        }}
        onNavigationStateChange={(navState) => {
          canGoBackRef.current = navState.canGoBack;
          const navOrigin = originOf(navState.url);
          if (/^https:\/\//i.test(navOrigin) && navOrigin !== origin) {
            portalOriginRef.current = navOrigin;
          }
        }}
        onShouldStartLoadWithRequest={(request) => {
          // Keep the shell on the configured server and let forward-auth
          // redirects (off-origin, non-click) load in-WebView so login can
          // complete; only clicked external links (Ko-fi, docs, SpoolmanDB)
          // open in the system browser.
          if (!shouldOpenExternally(request.url, request.navigationType, origin)) {
            return true;
          }
          Linking.openURL(request.url).catch(() => {});
          return false;
        }}
      />

      <View style={styles.fabColumn} pointerEvents="box-none">
        <Fab label="⚙" accessibilityLabel="Server settings" onPress={handleSettings} small />
        {nfcAvailable && (
          <Fab label="NFC" accessibilityLabel="Scan an NFC spool tag" onPress={handleNfcPress} />
        )}
        <Fab
          label="SCAN"
          accessibilityLabel="Scan a QR code or barcode"
          onPress={() => setScannerOpen(true)}
        />
      </View>

      <SettingsMenuModal
        visible={settingsOpen}
        title={profile.name ?? "Server"}
        subtitle={profile.baseUrl}
        entries={buildSettingsMenuEntries(Platform.OS)}
        onSelect={onSettingsSelect}
        onClose={() => setSettingsOpen(false)}
      />
      <ScannerModal
        visible={scannerOpen}
        onClose={() => setScannerOpen(false)}
        onScanned={handleScanned}
      />
      <NfcModal
        visible={nfcStatus !== null && Platform.OS === "android"}
        status={nfcStatus ?? ""}
        onCancel={() => {
          cancelNfcRead();
          setNfcStatus(null);
        }}
      />

      {/* Mounted per open: reads the app identity natively and seeds the
          domain prefill from the latest portal detection at that moment. */}
      {passkeySetupOpen && (
        <PasskeySetupModal
          visible
          initialDomain={hostOf(profile.authOrigin ?? portalOriginRef.current ?? origin)}
          onClose={() => setPasskeySetupOpen(false)}
        />
      )}

      {updateStatus !== null && (
        <View style={styles.updateOverlay} pointerEvents="auto">
          <ActivityIndicator size="large" color="#dc7734" />
          <Text style={styles.updateText}>{updateStatus}</Text>
        </View>
      )}
    </View>
  );
}

function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}

/** "https://auth.example.com" -> "auth.example.com" for the domain input. */
function hostOf(origin: string): string {
  return origin.replace(/^https?:\/\//i, "");
}

function errorMessage(e: unknown): string {
  if (e instanceof ApiError && e.status === 401) {
    return "The server rejected the request (401). Set the API token in the app, or log in inside the web UI.";
  }
  return e instanceof Error ? e.message : String(e);
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#000000",
  },
  webview: {
    flex: 1,
  },
  fabColumn: {
    position: "absolute",
    right: 16,
    bottom: 24,
    alignItems: "center",
    gap: 12,
  },
  updateOverlay: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(0,0,0,0.7)",
    gap: 16,
  },
  updateText: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "600",
  },
});
