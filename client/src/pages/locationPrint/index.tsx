import { PageHeader } from "@refinedev/antd";
import { useTranslate } from "@refinedev/core";
import { theme } from "antd";
import { Content } from "antd/es/layout/layout";
import { useNavigate, useSearchParams } from "react-router";
import LocationQRCodePrintingDialog from "../printing/locationQrCodePrintingDialog";
import LocationSelectModal from "../printing/locationSelectModal";

const { useToken } = theme;

/**
 * Location label printing page (#84), mirroring the spool print page: pick locations, then render
 * their scannable QR labels. Reached from the location show page ("Print label") or the board.
 */
export const LocationPrinting = () => {
  const { token } = useToken();
  const t = useTranslate();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const locationIds = searchParams.getAll("locations").map(Number);
  const step = locationIds.length > 0 ? 1 : 0;

  return (
    <PageHeader
      title={t("locations.print.title")}
      onBack={() => {
        const returnUrl = searchParams.get("return");
        if (returnUrl) {
          navigate(returnUrl, { relative: "path" });
        } else {
          navigate("/locations");
        }
      }}
    >
      <Content
        style={{
          padding: 20,
          minHeight: 280,
          margin: "0 auto",
          backgroundColor: token.colorBgContainer,
          borderRadius: token.borderRadiusLG,
          color: token.colorText,
          fontFamily: token.fontFamily,
          fontSize: token.fontSizeLG,
          lineHeight: 1.5,
        }}
      >
        {step === 0 && (
          <LocationSelectModal
            description={t("locations.print.description")}
            onContinue={(ids) => {
              setSearchParams((prev) => {
                const newParams = new URLSearchParams(prev);
                newParams.delete("locations");
                ids.forEach((id) => newParams.append("locations", id.toString()));
                newParams.set("return", "/location/print");
                return newParams;
              });
            }}
          />
        )}
        {step === 1 && <LocationQRCodePrintingDialog locationIds={locationIds} />}
      </Content>
    </PageHeader>
  );
};

export default LocationPrinting;
