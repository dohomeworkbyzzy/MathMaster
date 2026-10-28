plugins { id("com.android.application") }
android {
    namespace = "com.mathmaster.mobile"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.mathmaster.mobile"
        minSdk = 26
        targetSdk = 34
        versionCode = 2
        versionName = "0.1.1"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
