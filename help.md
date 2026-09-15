## A. Python実行環境を作成する
1. 下記サイトから同じバージョンのinstallerとembeddable packageをダウンロードする<br>
    [Python Releases for Windows](https://www.python.org/downloads/windows/)

2. embeddable packageを任意の場所に展開する

3. `python3xx.._pth`を編集
    ```
    python3xx.zip
    .
    
    #import site
    ```
    
    を、
    
    ```
    python3xx.zip
    .
    Lib
    Lib\site-packages
    
    import site
    ```
    
    に変更します。

4. インストール版Pythonをインストールする
5. `ensurepip` をコピーする
    インストール版から、

    ```
    ...\Python3xx\Lib\ensurepip
    ```
    
    を丸ごとコピーします。
    
    コピー先：

    ```
    ...\PortablePython\Lib\ensurepip
    ```

6. embeddable packageにpipを導入する
    ```
    C:\PortablePython\python.exe -m ensurepip --default-pip
    ```

7. tkinterをコピーする

    ここはpipより少し部品が多いです。
    
    インストール版からまず、
    
    ```text
    C:\Python314\Lib\tkinter
    ```
    
    を、
    
    ```text
    C:\PortablePython\Lib\tkinter
    ```
    
    へコピーします。
    
    次に、Tcl/Tkのスクリプト群をコピーします。
    
    インストール版の、
    
    ```text
    C:\Python314\tcl
    ```
    
    を丸ごと、
    
    ```text
    C:\PortablePython\tcl
    ```
    
    へコピーします。
    
    さらに、Tkinterが利用するネイティブ拡張、
    
    ```text
    _tkinter.pyd
    ```
    
    も必要です。
    
    通常は、
    
    ```text
    C:\Python314\DLLs\_tkinter.pyd
    ```
    
    にあります。
    
    これを例えば、
    
    ```text
    C:\PortablePython\_tkinter.pyd
    ```
    
    または、
    
    ```text
    C:\PortablePython\DLLs\_tkinter.pyd
    ```
    
    へコピーします。
    
    DLLsフォルダを使うなら、`python314._pth` に、
    
    ```text
    DLLs
    ```
    
    も追加します。
    
    例えば：
    
    ```text
    python314.zip
    .
    DLLs
    Lib
    Lib\site-packages
    
    import site
    ```
    
    ---

8. Tcl/Tk DLLもコピーする

    さらにTkそのもののDLLが必要です。
    
    インストール版の、
    
    ```text
    C:\Python314\DLLs\
    ```
    
    には通常、
    
    ```text
    tcl*.dll
    tk*.dll
    ```
    
    があります。
    
    例えばバージョンによって、
    
    ```text
    tcl86t.dll
    tk86t.dll
    ```
    
    などです。
    
    これらも、
    
    ```text
    C:\PortablePython\DLLs\
    ```
    
    へコピーします。
    
    結果として、
    
    ```text
    PortablePython\
    ├─ python.exe
    ├─ python314.dll
    ├─ python314.zip
    ├─ python314._pth
    │
    ├─ DLLs\
    │   ├─ _tkinter.pyd
    │   ├─ tcl....dll
    │   └─ tk....dll
    │
    ├─ Lib\
    │   ├─ ensurepip\
    │   ├─ tkinter\
    │   └─ site-packages\
    │
    └─ tcl\
        ├─ tcl8.x\
        └─ tk8.x\
    ```
    
    という構造になります。
    
    ---

9. tkinterを確認する

    ここまでできたら、
    
    ```bat
    C:\PortablePython\python.exe -m tkinter
    ```
    
    を実行します。
    
    Tkの小さなウィンドウが表示されれば成功です。
    
    もし、
    
    ```text
    ModuleNotFoundError: No module named '_tkinter'
    ```
    
    なら、
    
    ```text
    _tkinter.pyd
    ```
    
    の配置または検索パスが問題です。
    
    もし、
    
    ```text
    Can't find a usable init.tcl
    ```
    
    のようなエラーなら、
    
    ```text
    tcl\
    ```
    
    配下のスクリプトが見つかっていません。
    
    その場合は起動BATで明示的に、
    
    ```bat
    set "TCL_LIBRARY=%~dp0tcl\tcl8.6"
    set "TK_LIBRARY=%~dp0tcl\tk8.6"
    ```
    
    などを指定する方法もあります。
    
    実際のディレクトリ名に合わせてください。
    
    ---

10. `venv`を使いたい場合

    ここは少し注意があります。
    
    通常版の、
    
    ```text
    C:\Python314\Lib\venv
    ```
    
    を、
    
    ```text
    C:\PortablePython\Lib\venv
    ```
    
    へコピーすると、
    
    ```bat
    python.exe -m venv testenv
    ```
    
    が動く場合があります。
    
    ただし `venv` は標準ライブラリ本体だけではなく、実行環境やpipブートストラップなどとの組み合わせがあります。
    
    少なくとも、
    
    ```text
    Lib\venv
    Lib\ensurepip
    ```
    
    は揃えておく必要があります。
    
    確認：
    
    ```bat
    C:\PortablePython\python.exe -m venv C:\temp\testenv
    ```
    
    そして、
    
    ```bat
    C:\temp\testenv\Scripts\python.exe --version
    ```
    
    を試します。
    
    ただしUSBポータブル用途では、前述のようにvenv内部に元Pythonへのパス情報が残るので、USBのドライブ文字変更には弱いです。

11. パッケージインストール
    `python314._pth` は、

    ```text
    python314.zip
    .
    DLLs
    Lib
    Lib\site-packages
    
    import site
    ```
    
    です。
    
    作成時の確認は、
    
    ```bat
    python.exe --version
    python.exe -c "import ensurepip; print(ensurepip.version())"
    python.exe -m ensurepip --default-pip
    python.exe -m pip --version
    python.exe -m tkinter
    python.exe -m venv testenv
    ```
    
    の順番が分かりやすいです。
    
    これが全て成功したら、その `PortablePython` フォルダ全体をUSBへコピーします。
    
    そしてオフライン端末では、
    
    ```bat
    USB:\PortablePython\python.exe
    ```
    
    から起動できます。
    
    さらに第三者パッケージについては、オンライン端末で事前に、
    
    ```bat
    python -m pip download -d wheelhouse -r requirements.txt
    ```
    
    しておき、オフライン側では、
    
    ```bat
    python.exe -m pip install ^
        --no-index ^
        --find-links=wheelhouse ^
        -r requirements.txt
    ```
    
    とすればよいです。
