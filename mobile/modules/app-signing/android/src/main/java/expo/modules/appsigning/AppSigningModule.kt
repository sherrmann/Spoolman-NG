package expo.modules.appsigning

import android.content.pm.PackageManager
import android.content.pm.Signature
import android.os.Build
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.security.MessageDigest

class AppSigningModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("AppSigning")

    // SHA-256 fingerprints (colon-delimited uppercase hex, apksigner style) of
    // the certificates this APK is signed with — what assetlinks.json must list.
    Function("getSigningCertSha256") {
      val context = appContext.reactContext ?: return@Function emptyList<String>()
      val signatures: Array<Signature> =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
          val info = context.packageManager.getPackageInfo(
            context.packageName,
            PackageManager.GET_SIGNING_CERTIFICATES,
          )
          val signingInfo = info.signingInfo
          when {
            signingInfo == null -> emptyArray()
            signingInfo.hasMultipleSigners() -> signingInfo.apkContentsSigners
            // Single signer: the history covers past certs after a key
            // rotation too — any of them satisfies a DAL match.
            else -> signingInfo.signingCertificateHistory ?: emptyArray()
          }
        } else {
          @Suppress("DEPRECATION")
          context.packageManager.getPackageInfo(
            context.packageName,
            PackageManager.GET_SIGNATURES,
          ).signatures ?: emptyArray()
        }
      signatures.map { signature ->
        MessageDigest.getInstance("SHA-256")
          .digest(signature.toByteArray())
          .joinToString(":") { byte -> "%02X".format(byte) }
      }
    }
  }
}
