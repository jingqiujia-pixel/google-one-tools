// launch_checkout.js —— 注入 Google One，查询指定 SKU 并拉起 Play 收银台
//
// 用法：由 launch_checkout.py 加载，改下面 TARGET_PRODUCT 即可换档。
// 结果通过 send() 事件发回：setup / products / offer / launched / purchase_cb 等。
// 【不会自动点「订阅」】，弹出的收银台由人工确认。
var TARGET_PRODUCT = "g1.20tb";   // ← 改这里换 SKU（见 README 的 SKU 对照表）
var TARGET_OFFER = "";            // ← 留空=第一个 offer；填 offerId 可指定（如 eft-12mo）
var MODULE_APK = "/data/local/tmp/module_521.apk";

Java.perform(function () {
    var context = Java.use("android.app.ActivityThread").currentApplication().getApplicationContext();
    var Activity = Java.use("android.app.Activity");
    var ArrayList = Java.use("java.util.ArrayList");
    var List = Java.use("java.util.List");
    var Handler = Java.use("android.os.Handler");
    var Looper = Java.use("android.os.Looper");

    // --- 从模块 APK 里加载 BillingClient（Google One 自身不带计费库）---
    var DexClassLoader = Java.use("dalvik.system.DexClassLoader");
    var dexLoader = DexClassLoader.$new(
        MODULE_APK,
        context.getCodeCacheDir().getAbsolutePath(),
        null,
        context.getClassLoader()
    );
    Java.classFactory.loader = dexLoader;

    var BillingClient = Java.use("com.android.billingclient.api.BillingClient");
    var QueryProductDetailsParams = Java.use("com.android.billingclient.api.QueryProductDetailsParams");
    var QpdProduct = Java.use("com.android.billingclient.api.QueryProductDetailsParams$Product");
    var BillingFlowParams = Java.use("com.android.billingclient.api.BillingFlowParams");
    var BfpProductDetailsParams = Java.use("com.android.billingclient.api.BillingFlowParams$ProductDetailsParams");
    var PurchasesUpdatedListener = Java.use("com.android.billingclient.api.PurchasesUpdatedListener");
    var BillingClientStateListener = Java.use("com.android.billingclient.api.BillingClientStateListener");
    var ProductDetailsResponseListener = Java.use("com.android.billingclient.api.ProductDetailsResponseListener");
    var ProductDetails = Java.use("com.android.billingclient.api.ProductDetails");
    var SubscriptionOfferDetails = Java.use("com.android.billingclient.api.ProductDetails$SubscriptionOfferDetails");
    var PricingPhase = Java.use("com.android.billingclient.api.ProductDetails$PricingPhase");

    function S(o) { try { send(o); } catch (e) {} }

    // --- 购买结果回调（用户在收银台点确认/取消后触发）---
    var purchaseListener = Java.registerClass({
        name: "com.frida.paid.PL",
        implements: [PurchasesUpdatedListener],
        methods: {
            onPurchasesUpdated: function (br, purchases) {
                S({ ev: "purchase_cb", code: br.getResponseCode(), msg: String(br.getDebugMessage() || "") });
            }
        }
    }).$new();

    // enablePendingPurchases 必须调，否则 build() 可能直接抛异常
    var bc = BillingClient.newBuilder(context).setListener(purchaseListener).enablePendingPurchases().build();

    // --- 连接结算服务：连上后把查询任务 post 到主线程 ---
    var stateListener = Java.registerClass({
        name: "com.frida.paid.SL",
        implements: [BillingClientStateListener],
        methods: {
            onBillingSetupFinished: function (result) {
                S({ ev: "setup", code: result.getResponseCode() });
                if (result.getResponseCode() !== 0) return;
                Java.classFactory.loader = null;
                var mainHandler = Handler.$new(Looper.getMainLooper());
                Java.classFactory.loader = dexLoader;
                var Runnable = Java.use("java.lang.Runnable");
                mainHandler.post(Java.registerClass({
                    name: "com.frida.paid.QR",
                    implements: [Runnable],
                    methods: { run: function () { doQuery(); } }
                }).$new());
            },
            onBillingServiceDisconnected: function () { S({ ev: "disc" }); }
        }
    }).$new();

    function doQuery() {
        var prodList = ArrayList.$new();
        prodList.add(QpdProduct.newBuilder().setProductId(TARGET_PRODUCT).setProductType("subs").build());
        var params = QueryProductDetailsParams.newBuilder().setProductList(prodList).build();
        bc.queryProductDetailsAsync(params, Java.registerClass({
            name: "com.frida.paid.PDL",
            implements: [ProductDetailsResponseListener],
            methods: { onProductDetailsResponse: function (br, pdList) { onProducts(br, pdList); } }
        }).$new());
    }

    // --- 通过 ActivityThread.mActivities 反射拿前台 Activity（比 Java.choose 稳）---
    function getActivity() {
        try {
            Java.classFactory.loader = null;
            var AT = Java.use("android.app.ActivityThread");
            var acts = AT.currentActivityThread().mActivities.value;
            var it = acts.values().iterator();
            while (it.hasNext()) {
                var rec = it.next();
                var f = rec.getClass().getDeclaredField("activity");
                f.setAccessible(true);
                var a = Java.cast(f.get(rec), Activity);
                if (!a.isFinishing() && !a.isDestroyed()) { Java.classFactory.loader = dexLoader; return a; }
            }
            Java.classFactory.loader = dexLoader;
        } catch (e) {
            Java.classFactory.loader = dexLoader;
            S({ ev: "act_err", m: String(e) });
        }
        return null;
    }

    function onProducts(br, pdList) {
        var list = Java.cast(pdList, List);
        S({ ev: "products", n: list.size() });

        // 取目标 SKU 的第一个 offer（= 基础付费档）
        var targetPd = null, targetOffer = null;
        for (var i = 0; i < list.size(); i++) {
            var pd = Java.cast(list.get(i), ProductDetails);
            var pid = String(pd.getProductId());
            var offers = pd.getSubscriptionOfferDetails();
            if (offers == null) continue;
            var ol = Java.cast(offers, List);
            for (var j = 0; j < ol.size(); j++) {
                var o = Java.cast(ol.get(j), SubscriptionOfferDetails);
                var first = Java.cast(Java.cast(o.getPricingPhases().getPricingPhaseList(), List).get(0), PricingPhase);
                S({ ev: "offer", product: pid, id: String(o.getOfferId()),
                    micros: String(first.getPriceAmountMicros()),
                    period: String(first.getBillingPeriod()) });
                if (pid === TARGET_PRODUCT && targetPd == null && (!TARGET_OFFER || String(o.getOfferId()) === TARGET_OFFER)) { targetPd = pd; targetOffer = o; }
            }
        }
        if (!targetPd || !targetOffer) { S({ ev: "no_offer" }); return; }

        var token = targetOffer.getOfferToken();
        var finalPd = targetPd, finalToken = token;

        // 延迟 1.5s 再在 UI 线程拉收银台，等 Activity 渲染稳定
        Java.classFactory.loader = null;
        var launchHandler = Handler.$new(Looper.getMainLooper());
        Java.classFactory.loader = dexLoader;
        launchHandler.postDelayed(Java.registerClass({
            name: "com.frida.paid.LR",
            implements: [Java.use("java.lang.Runnable")],
            methods: {
                run: function () {
                    try {
                        var uiAct = getActivity();          // UI 线程上重取当前 Activity
                        if (!uiAct) { S({ ev: "no_activity_ui" }); return; }
                        var pdp = BfpProductDetailsParams.newBuilder()
                            .setProductDetails(finalPd).setOfferToken(finalToken).build();
                        var l = ArrayList.$new(); l.add(pdp);
                        var flowParams = BillingFlowParams.newBuilder().setProductDetailsParamsList(l).build();
                        var r = bc.launchBillingFlow(Java.cast(uiAct, Activity), flowParams);
                        S({ ev: "launched", code: r.getResponseCode(), msg: String(r.getDebugMessage() || "") });
                    } catch (e) { S({ ev: "launch_err", m: String(e) }); }
                }
            }
        }).$new(), 1500);
    }

    bc.startConnection(stateListener);
});
setInterval(function () {}, 1000);   // 保持脚本存活
