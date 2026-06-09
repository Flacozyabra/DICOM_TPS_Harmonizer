# План реализации: Совместимость с Monaco TPS (Specific Character Set, 16-bit alignment, CT table angles)

## 1. Изменения в конвертере (src/core/converter.py)
[MODIFY] [converter.py](file:///c:/Users/Falco/Desktop/DICOM%20TPS%20Harmonizer/src/core/converter.py)
- Принудительно устанавливать `SpecificCharacterSet` в `ISO_IR 100`.
- В случае, если исходное изображение имеет `BitsAllocated != 16`, переопределять теги `BitsAllocated = 16`, `BitsStored = 16`, `HighBit = 15`, чтобы гарантировать соответствие 16-битному массиву пикселей, который записывается конвертером.
- Для модальности `CT`, если заполнение тегов по умолчанию включено (`config.default_tags`), сбрасывать в 0 углы позиционирования стола: `PatientSupportAngle`, `TableTopPitchAngle`, `TableTopRollAngle` (теги `300A,0122`, `300A,0140`, `300A,0144`).

## План проверки
1. Запустить проверку компиляции синтаксиса `converter.py`.
2. Проверить создание DICOM файлов:
   - Убедиться, что Specific Character Set равен `ISO_IR 100`.
   - Убедиться, что для 8-битных или нестандартных файлов `BitsAllocated` корректируется до 16.
   - Убедиться, что для CT файлов углы стола обнуляются.
