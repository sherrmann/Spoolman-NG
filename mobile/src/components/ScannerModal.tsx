import { CameraView, useCameraPermissions, type BarcodeType } from "expo-camera";
import React, { useEffect, useRef } from "react";
import { Linking, Modal, StyleSheet, Text, TouchableOpacity, View } from "react-native";

// The formats the web scanner decodes (client/src/components/qrCodeScanner.tsx),
// minus micro-QR/rM-QR (not supported by MLKit/AVFoundation), plus code128 for
// the 1-D labels Spoolman prints (client/src/utils/barcode.ts).
const BARCODE_TYPES: BarcodeType[] = [
  "qr",
  "datamatrix",
  "aztec",
  "pdf417",
  "ean13",
  "ean8",
  "upc_a",
  "upc_e",
  "code128",
];

interface ScannerModalProps {
  visible: boolean;
  onClose: () => void;
  onScanned: (data: string) => void;
}

export function ScannerModal({ visible, onClose, onScanned }: ScannerModalProps) {
  const [permission, requestPermission] = useCameraPermissions();
  const handledRef = useRef(false);

  useEffect(() => {
    if (visible) {
      handledRef.current = false;
      if (permission && !permission.granted && permission.canAskAgain) {
        requestPermission();
      }
    }
    // Ask only when the modal opens; `permission` updating must not re-trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const denied = permission != null && !permission.granted && !permission.canAskAgain;

  return (
    <Modal visible={visible} animationType="slide" onRequestClose={onClose}>
      <View style={styles.container}>
        {permission?.granted ? (
          <CameraView
            style={styles.camera}
            facing="back"
            barcodeScannerSettings={{ barcodeTypes: BARCODE_TYPES }}
            onBarcodeScanned={({ data }) => {
              if (handledRef.current || !data) {
                return;
              }
              handledRef.current = true;
              onScanned(data);
            }}
          />
        ) : (
          <View style={styles.message}>
            <Text style={styles.messageText}>
              {denied
                ? "Camera access is denied. Allow it in the system settings to scan codes."
                : "Camera permission is required to scan spool codes."}
            </Text>
            {denied && (
              <TouchableOpacity style={styles.settingsButton} onPress={() => Linking.openSettings()}>
                <Text style={styles.settingsButtonText}>Open settings</Text>
              </TouchableOpacity>
            )}
          </View>
        )}
        <View style={styles.overlay} pointerEvents="box-none">
          <Text style={styles.hint}>Point the camera at a spool QR code or barcode</Text>
          <TouchableOpacity style={styles.cancel} onPress={onClose} accessibilityRole="button">
            <Text style={styles.cancelText}>Cancel</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#000000",
  },
  camera: {
    flex: 1,
  },
  message: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: 32,
  },
  messageText: {
    color: "#ffffff",
    fontSize: 16,
    textAlign: "center",
  },
  settingsButton: {
    marginTop: 16,
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 8,
    backgroundColor: "#dc7734",
  },
  settingsButtonText: {
    color: "#ffffff",
    fontWeight: "600",
  },
  overlay: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    padding: 24,
    alignItems: "center",
  },
  hint: {
    color: "#ffffff",
    backgroundColor: "rgba(0,0,0,0.55)",
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 8,
    marginBottom: 16,
    textAlign: "center",
  },
  cancel: {
    paddingVertical: 12,
    paddingHorizontal: 32,
    borderRadius: 24,
    backgroundColor: "rgba(255,255,255,0.15)",
  },
  cancelText: {
    color: "#ffffff",
    fontSize: 16,
    fontWeight: "600",
  },
});
