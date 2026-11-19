#!/usr/bin/env python3
"""Genera AutoGPTWatch.xcodeproj de forma determinista.

Usa carpetas sincronizadas (PBXFileSystemSynchronizedRootGroup, Xcode 16+): cualquier
archivo .swift o recurso dentro de ios/AutoGPTWatch/ se incluye automáticamente en el
target, sin listar archivos uno a uno. El paquete local Packages/AutoGPTCore se enlaza
como dependencia Swift Package.

Uso:  python3 ios/tools/generate_xcodeproj.py
Alternativa: `xcodegen generate` con ios/project.yml.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

IOS = Path(__file__).resolve().parents[1]
PROJECT = IOS / "AutoGPTWatch.xcodeproj"

APP = "AutoGPTWatch"
BUNDLE_ID = "com.example.autogptwatch"  # cámbialo por uno propio (p. ej. com.tunombre.autogptwatch)
DEPLOYMENT_TARGET = "17.0"


def oid(name: str) -> str:
    return hashlib.md5(name.encode()).hexdigest()[:24].upper()


IDS = {k: oid(k) for k in [
    "project", "main_group", "products_group", "config_group",
    "app_target", "app_product", "app_sync",
    "app_sources", "app_frameworks", "app_resources",
    "core_pkg_ref", "core_product_dep", "core_buildfile",
    "info_plist_ref", "entitlements_ref", "entitlements_nopush_ref",
    "proj_config_list", "proj_debug", "proj_release",
    "app_config_list", "app_debug", "app_release",
]}


def q(v: str) -> str:
    """Entrecomilla valores de pbxproj cuando hace falta."""
    import re

    if v and re.fullmatch(r"[A-Za-z0-9_./$]+", v):
        return v
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def settings_block(d: dict[str, object], indent: str = "\t\t\t\t") -> str:
    lines = []
    for k in sorted(d):
        v = d[k]
        if isinstance(v, list):
            inner = "".join(f"{indent}\t{q(x)},\n" for x in v)
            lines.append(f"{indent}{k} = (\n{inner}{indent});\n")
        else:
            lines.append(f"{indent}{k} = {q(str(v))};\n")
    return "".join(lines)


COMMON_PROJECT = {
    "ALWAYS_SEARCH_USER_PATHS": "NO",
    "CLANG_ENABLE_MODULES": "YES",
    "CLANG_ENABLE_OBJC_ARC": "YES",
    "COPY_PHASE_STRIP": "NO",
    "ENABLE_STRICT_OBJC_MSGSEND": "YES",
    "ENABLE_USER_SCRIPT_SANDBOXING": "YES",
    "GCC_C_LANGUAGE_STANDARD": "gnu17",
    "IPHONEOS_DEPLOYMENT_TARGET": DEPLOYMENT_TARGET,
    "LOCALIZATION_PREFERS_STRING_CATALOGS": "YES",
    "SDKROOT": "iphoneos",
    "SWIFT_VERSION": "5.0",
}
PROJECT_DEBUG = {
    **COMMON_PROJECT,
    "DEBUG_INFORMATION_FORMAT": "dwarf",
    "ENABLE_TESTABILITY": "YES",
    "GCC_OPTIMIZATION_LEVEL": "0",
    "GCC_PREPROCESSOR_DEFINITIONS": ["DEBUG=1", "$(inherited)"],
    "ONLY_ACTIVE_ARCH": "YES",
    "SWIFT_ACTIVE_COMPILATION_CONDITIONS": "DEBUG $(inherited)",
    "SWIFT_OPTIMIZATION_LEVEL": "-Onone",
}
PROJECT_RELEASE = {
    **COMMON_PROJECT,
    "DEBUG_INFORMATION_FORMAT": "dwarf-with-dsym",
    "ENABLE_NS_ASSERTIONS": "NO",
    "SWIFT_COMPILATION_MODE": "wholemodule",
    "VALIDATE_PRODUCT": "YES",
}
APP_COMMON = {
    "ASSETCATALOG_COMPILER_APPICON_NAME": "AppIcon",
    "ASSETCATALOG_COMPILER_GLOBAL_ACCENT_COLOR_NAME": "AccentColor",
    "CODE_SIGN_ENTITLEMENTS": "Config/AutoGPTWatch.entitlements",
    "CODE_SIGN_STYLE": "Automatic",
    "CURRENT_PROJECT_VERSION": "1",
    "DEVELOPMENT_TEAM": "",
    "ENABLE_PREVIEWS": "YES",
    "GENERATE_INFOPLIST_FILE": "YES",
    "INFOPLIST_FILE": "Config/Info.plist",
    "INFOPLIST_KEY_CFBundleDisplayName": "AutoGPT Watch",
    "INFOPLIST_KEY_LSApplicationCategoryType": "public.app-category.productivity",
    "INFOPLIST_KEY_UIApplicationSceneManifest_Generation": "YES",
    "INFOPLIST_KEY_UILaunchScreen_Generation": "YES",
    "INFOPLIST_KEY_UISupportedInterfaceOrientations": "UIInterfaceOrientationPortrait",
    "INFOPLIST_KEY_UIUserInterfaceStyle": "Dark",
    "LD_RUNPATH_SEARCH_PATHS": ["$(inherited)", "@executable_path/Frameworks"],
    "MARKETING_VERSION": "1.0",
    "PRODUCT_BUNDLE_IDENTIFIER": BUNDLE_ID,
    "PRODUCT_NAME": "$(TARGET_NAME)",
    "SUPPORTED_PLATFORMS": "iphoneos iphonesimulator",
    "SUPPORTS_MACCATALYST": "NO",
    "SWIFT_EMIT_LOC_STRINGS": "YES",
    "TARGETED_DEVICE_FAMILY": "1",
}


def build() -> str:
    i = IDS
    return f"""// !$*UTF8*$!
{{
	archiveVersion = 1;
	classes = {{
	}};
	objectVersion = 77;
	objects = {{

/* Begin PBXBuildFile section */
		{i['core_buildfile']} /* AutoGPTCore in Frameworks */ = {{isa = PBXBuildFile; productRef = {i['core_product_dep']} /* AutoGPTCore */; }};
/* End PBXBuildFile section */

/* Begin PBXFileReference section */
		{i['app_product']} /* {APP}.app */ = {{isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = {APP}.app; sourceTree = BUILT_PRODUCTS_DIR; }};
		{i['info_plist_ref']} /* Info.plist */ = {{isa = PBXFileReference; lastKnownFileType = text.plist.xml; path = Info.plist; sourceTree = "<group>"; }};
		{i['entitlements_ref']} /* AutoGPTWatch.entitlements */ = {{isa = PBXFileReference; lastKnownFileType = text.plist.entitlements; path = AutoGPTWatch.entitlements; sourceTree = "<group>"; }};
		{i['entitlements_nopush_ref']} /* AutoGPTWatch-NoPush.entitlements */ = {{isa = PBXFileReference; lastKnownFileType = text.plist.entitlements; path = "AutoGPTWatch-NoPush.entitlements"; sourceTree = "<group>"; }};
/* End PBXFileReference section */

/* Begin PBXFileSystemSynchronizedRootGroup section */
		{i['app_sync']} /* {APP} */ = {{
			isa = PBXFileSystemSynchronizedRootGroup;
			path = {APP};
			sourceTree = "<group>";
		}};
/* End PBXFileSystemSynchronizedRootGroup section */

/* Begin PBXFrameworksBuildPhase section */
		{i['app_frameworks']} /* Frameworks */ = {{
			isa = PBXFrameworksBuildPhase;
			buildActionMask = 2147483647;
			files = (
				{i['core_buildfile']} /* AutoGPTCore in Frameworks */,
			);
			runOnlyForDeploymentPostprocessing = 0;
		}};
/* End PBXFrameworksBuildPhase section */

/* Begin PBXGroup section */
		{i['main_group']} = {{
			isa = PBXGroup;
			children = (
				{i['app_sync']} /* {APP} */,
				{i['config_group']} /* Config */,
				{i['products_group']} /* Products */,
			);
			sourceTree = "<group>";
		}};
		{i['config_group']} /* Config */ = {{
			isa = PBXGroup;
			children = (
				{i['info_plist_ref']} /* Info.plist */,
				{i['entitlements_ref']} /* AutoGPTWatch.entitlements */,
				{i['entitlements_nopush_ref']} /* AutoGPTWatch-NoPush.entitlements */,
			);
			path = Config;
			sourceTree = "<group>";
		}};
		{i['products_group']} /* Products */ = {{
			isa = PBXGroup;
			children = (
				{i['app_product']} /* {APP}.app */,
			);
			name = Products;
			sourceTree = "<group>";
		}};
/* End PBXGroup section */

/* Begin PBXNativeTarget section */
		{i['app_target']} /* {APP} */ = {{
			isa = PBXNativeTarget;
			buildConfigurationList = {i['app_config_list']} /* Build configuration list for PBXNativeTarget "{APP}" */;
			buildPhases = (
				{i['app_sources']} /* Sources */,
				{i['app_frameworks']} /* Frameworks */,
				{i['app_resources']} /* Resources */,
			);
			buildRules = (
			);
			dependencies = (
			);
			fileSystemSynchronizedGroups = (
				{i['app_sync']} /* {APP} */,
			);
			name = {APP};
			packageProductDependencies = (
				{i['core_product_dep']} /* AutoGPTCore */,
			);
			productName = {APP};
			productReference = {i['app_product']} /* {APP}.app */;
			productType = "com.apple.product-type.application";
		}};
/* End PBXNativeTarget section */

/* Begin PBXProject section */
		{i['project']} /* Project object */ = {{
			isa = PBXProject;
			attributes = {{
				BuildIndependentTargetsInParallel = 1;
				LastSwiftUpdateCheck = 1600;
				LastUpgradeCheck = 1600;
				TargetAttributes = {{
					{i['app_target']} = {{
						CreatedOnToolsVersion = 16.0;
					}};
				}};
			}};
			buildConfigurationList = {i['proj_config_list']} /* Build configuration list for PBXProject "{APP}" */;
			developmentRegion = es;
			hasScannedForEncodings = 0;
			knownRegions = (
				es,
				en,
				Base,
			);
			mainGroup = {i['main_group']};
			minimizedProjectReferenceProxies = 1;
			packageReferences = (
				{i['core_pkg_ref']} /* XCLocalSwiftPackageReference "Packages/AutoGPTCore" */,
			);
			preferredProjectObjectVersion = 77;
			productRefGroup = {i['products_group']} /* Products */;
			projectDirPath = "";
			projectRoot = "";
			targets = (
				{i['app_target']} /* {APP} */,
			);
		}};
/* End PBXProject section */

/* Begin PBXResourcesBuildPhase section */
		{i['app_resources']} /* Resources */ = {{
			isa = PBXResourcesBuildPhase;
			buildActionMask = 2147483647;
			files = (
			);
			runOnlyForDeploymentPostprocessing = 0;
		}};
/* End PBXResourcesBuildPhase section */

/* Begin PBXSourcesBuildPhase section */
		{i['app_sources']} /* Sources */ = {{
			isa = PBXSourcesBuildPhase;
			buildActionMask = 2147483647;
			files = (
			);
			runOnlyForDeploymentPostprocessing = 0;
		}};
/* End PBXSourcesBuildPhase section */

/* Begin XCBuildConfiguration section */
		{i['proj_debug']} /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
{settings_block(PROJECT_DEBUG)}			}};
			name = Debug;
		}};
		{i['proj_release']} /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
{settings_block(PROJECT_RELEASE)}			}};
			name = Release;
		}};
		{i['app_debug']} /* Debug */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
{settings_block(APP_COMMON)}			}};
			name = Debug;
		}};
		{i['app_release']} /* Release */ = {{
			isa = XCBuildConfiguration;
			buildSettings = {{
{settings_block(APP_COMMON)}			}};
			name = Release;
		}};
/* End XCBuildConfiguration section */

/* Begin XCConfigurationList section */
		{i['proj_config_list']} /* Build configuration list for PBXProject "{APP}" */ = {{
			isa = XCConfigurationList;
			buildConfigurations = (
				{i['proj_debug']} /* Debug */,
				{i['proj_release']} /* Release */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Release;
		}};
		{i['app_config_list']} /* Build configuration list for PBXNativeTarget "{APP}" */ = {{
			isa = XCConfigurationList;
			buildConfigurations = (
				{i['app_debug']} /* Debug */,
				{i['app_release']} /* Release */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Release;
		}};
/* End XCConfigurationList section */

/* Begin XCLocalSwiftPackageReference section */
		{i['core_pkg_ref']} /* XCLocalSwiftPackageReference "Packages/AutoGPTCore" */ = {{
			isa = XCLocalSwiftPackageReference;
			relativePath = Packages/AutoGPTCore;
		}};
/* End XCLocalSwiftPackageReference section */

/* Begin XCSwiftPackageProductDependency section */
		{i['core_product_dep']} /* AutoGPTCore */ = {{
			isa = XCSwiftPackageProductDependency;
			productName = AutoGPTCore;
		}};
/* End XCSwiftPackageProductDependency section */
	}};
	rootObject = {i['project']} /* Project object */;
}}
"""


SCHEME = """<?xml version="1.0" encoding="UTF-8"?>
<Scheme LastUpgradeVersion = "1600" version = "1.7">
   <BuildAction parallelizeBuildables = "YES" buildImplicitDependencies = "YES">
      <BuildActionEntries>
         <BuildActionEntry buildForTesting = "YES" buildForRunning = "YES" buildForProfiling = "YES" buildForArchiving = "YES" buildForAnalyzing = "YES">
            <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{app}" BuildableName = "AutoGPTWatch.app" BlueprintName = "AutoGPTWatch" ReferencedContainer = "container:AutoGPTWatch.xcodeproj">
            </BuildableReference>
         </BuildActionEntry>
      </BuildActionEntries>
   </BuildAction>
   <TestAction buildConfiguration = "Debug" selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB" shouldUseLaunchSchemeArgsEnv = "YES" shouldAutocreateTestPlan = "YES">
      <Testables>
         <TestableReference skipped = "NO">
            <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "AutoGPTCoreTests" BuildableName = "AutoGPTCoreTests" BlueprintName = "AutoGPTCoreTests" ReferencedContainer = "container:Packages/AutoGPTCore">
            </BuildableReference>
         </TestableReference>
      </Testables>
   </TestAction>
   <LaunchAction buildConfiguration = "Debug" selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB" selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB" launchStyle = "0" useCustomWorkingDirectory = "NO" ignoresPersistentStateOnLaunch = "NO" debugDocumentVersioning = "YES" debugServiceExtension = "internal" allowLocationSimulation = "YES">
      <BuildableProductRunnable runnableDebuggingMode = "0">
         <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{app}" BuildableName = "AutoGPTWatch.app" BlueprintName = "AutoGPTWatch" ReferencedContainer = "container:AutoGPTWatch.xcodeproj">
         </BuildableReference>
      </BuildableProductRunnable>
   </LaunchAction>
   <ProfileAction buildConfiguration = "Release" shouldUseLaunchSchemeArgsEnv = "YES" savedToolIdentifier = "" useCustomWorkingDirectory = "NO" debugDocumentVersioning = "YES">
      <BuildableProductRunnable runnableDebuggingMode = "0">
         <BuildableReference BuildableIdentifier = "primary" BlueprintIdentifier = "{app}" BuildableName = "AutoGPTWatch.app" BlueprintName = "AutoGPTWatch" ReferencedContainer = "container:AutoGPTWatch.xcodeproj">
         </BuildableReference>
      </BuildableProductRunnable>
   </ProfileAction>
   <AnalyzeAction buildConfiguration = "Debug">
   </AnalyzeAction>
   <ArchiveAction buildConfiguration = "Release" revealArchiveInOrganizer = "YES">
   </ArchiveAction>
</Scheme>
"""


def check_balanced(text: str) -> None:
    """Validación sintáctica mínima: llaves y paréntesis balanceados fuera de comillas."""
    depth = {"{": 0, "(": 0}
    pairs = {"}": "{", ")": "("}
    in_str = False
    esc = False
    for ch in text:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in depth:
            depth[ch] += 1
        elif ch in pairs:
            depth[pairs[ch]] -= 1
            if depth[pairs[ch]] < 0:
                raise SystemExit("pbxproj desbalanceado")
    if any(depth.values()) or in_str:
        raise SystemExit(f"pbxproj desbalanceado: {depth}")


def main() -> None:
    text = build()
    check_balanced(text)
    PROJECT.mkdir(exist_ok=True)
    (PROJECT / "project.pbxproj").write_text(text)
    ws = PROJECT / "project.xcworkspace"
    ws.mkdir(exist_ok=True)
    (ws / "contents.xcworkspacedata").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<Workspace\n   version = "1.0">\n'
        '   <FileRef\n      location = "self:">\n   </FileRef>\n</Workspace>\n'
    )
    schemes = PROJECT / "xcshareddata" / "xcschemes"
    schemes.mkdir(parents=True, exist_ok=True)
    (schemes / "AutoGPTWatch.xcscheme").write_text(SCHEME.replace("{app}", IDS["app_target"]))
    print(f"Generado {PROJECT}")


if __name__ == "__main__":
    main()
