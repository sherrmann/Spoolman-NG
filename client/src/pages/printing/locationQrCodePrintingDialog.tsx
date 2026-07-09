import { useTranslate } from "@refinedev/core";
import { parseStringSettingValue, useGetSetting } from "../../utils/querySettings";
import { useSavedState } from "../../utils/saveload";
import { useGetLocationsByIds } from "../locations/functions";
import { ILocation } from "../locations/model";
import { QRCodePrintSettings } from "./printing";
import QRCodePrintingDialog from "./qrCodePrintingDialog";

/**
 * Print scannable QR labels for storage locations (#84). Locations are simple (a name and optional
 * comment), so unlike the spool/filament dialogs this needs no template editor or multi-preset
 * machinery — a single persisted label preset drives the generic QRCodePrintingDialog. The QR
 * encodes the `L-<id>` scheme (or the deep-link URL), which the scanner resolves to the location
 * show page.
 */
const LocationQRCodePrintingDialog = ({ locationIds }: { locationIds: number[] }) => {
  const t = useTranslate();
  const baseUrlSetting = useGetSetting("base_url");
  const baseUrl = parseStringSettingValue(baseUrlSetting.data?.value);
  const baseUrlRoot = baseUrl !== "" ? baseUrl : window.location.origin;
  const [useHTTPUrl, setUseHTTPUrl] = useSavedState("print-useHTTPUrl", false);
  const [labelSettings, setLabelSettings] = useSavedState<QRCodePrintSettings>("locationPrintSettings", {
    printSettings: { id: "location-default", name: t("locations.location") },
  });

  const itemQueries = useGetLocationsByIds(locationIds);
  const locations = itemQueries.map((q) => q.data ?? null).filter((l): l is ILocation => l !== null);

  return (
    <QRCodePrintingDialog
      printSettings={labelSettings}
      setPrintSettings={setLabelSettings}
      baseUrlRoot={baseUrlRoot}
      useHTTPUrl={useHTTPUrl}
      setUseHTTPUrl={setUseHTTPUrl}
      previewValues={{
        default: "WEB+SPOOLMAN:L-{id}",
        url: `${baseUrlRoot}/location/show/{id}`,
      }}
      items={locations.map((loc) => ({
        value: useHTTPUrl ? `${baseUrlRoot}/location/show/${loc.id}` : `WEB+SPOOLMAN:L-${loc.id}`,
        label: (
          <p style={{ padding: "1mm 1mm 1mm 0", margin: 0, whiteSpace: "pre-wrap" }}>
            {loc.name}
            {loc.comment ? `\n${loc.comment}` : ""}
          </p>
        ),
      }))}
    />
  );
};

export default LocationQRCodePrintingDialog;
